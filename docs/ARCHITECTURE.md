# Architecture

## Overview

```
GNOME shortcut ──▶ voice-input toggle --lang ru      (short-lived client)
                         │  starts the daemon if needed (detached, own session)
                         ▼
               $XDG_RUNTIME_DIR/voice-input/daemon.sock   (JSON lines, protocol v1)
                         │
                         ▼
 ┌──────────────────────── daemon ────────────────────────┐
 │ Controller (state machine)                              │
 │   idle ──toggle──▶ recording ──toggle──▶ transcribing ──┐│
 │    ▲                   │ cancel             │ worker    ││
 │    └───────────────────┴────────────────────┴───────────┘│
 │                                                          │
 │ Recorder ─ sounddevice/PortAudio, 16 kHz mono float32     │
 │ Transcriber ─ faster-whisper, models cached in memory     │
 │ Inserter ─ clipboard + primary, then Shift+Insert         │
 │ Feedback ─ notify-send bubble + sound cues                │
 └──────────────────────────────────────────────────────────┘
```

The client returns immediately. Recognition and typing run on a worker thread in the daemon, and
the user follows progress through notifications and tones.

## Modules (`src/voice_input/`)

| Module | Responsibility |
|---|---|
| `cli.py` | Argument parsing and the commands. Talks to the daemon or runs offline commands. |
| `config.py` | Settings: defaults, TOML file, `VOICE_INPUT_*` environment, validation. |
| `languages.py` | The supported languages and their parsing. |
| `controller.py` | The dictation state machine and the interfaces of its collaborators (`Recorder`, `Transcriber`, `Inserter`, `Feedback`). No I/O of its own, fully tested with fakes. |
| `daemon.py` | Builds the real collaborators, serves requests, preloads the model, handles signals. |
| `audio/recorder.py` | Microphone capture; falls back to the device's own rate and resamples. Calls back from a separate thread at the maximum duration (a PortAudio stream must not be stopped from its own callback). |
| `audio/signal.py` | Resampling, down-mixing, WAV reading and writing. |
| `audio/cues.py` | Generated tones. |
| `stt/whisper.py` | faster-whisper wrapper: lazy loading, per-language models, auto-detection limited to en/ru/he. |
| `postprocess.py` | Joins segments, normalises spaces, drops phantom subtitle phrases. |
| `insert/inserter.py` | Copies, then presses the paste keys; chooses the key backend. |
| `insert/clipboard.py`, `insert/xselection.py` | `wl-copy`, and an X11 selection owner written with python-xlib. |
| `insert/uinput.py` | A virtual keyboard through `/dev/uinput`, in pure Python (ioctl + struct). |
| `insert/keys.py` | Key names to Linux key codes. |
| `ipc/` | Protocol, server (single instance via `flock`), client (with on-demand start). |
| `desktop/` | Notifications, GNOME shortcuts (`gsettings`), systemd user unit, udev rule. |
| `doctor.py` | Installation checks with hints. |

## Why paste instead of typing

A virtual keyboard sends key codes, not characters. Which character a key code produces depends
on the active keyboard layout, so typing Russian or Hebrew text key by key only works if that
layout happens to be active. Pasting inserts any Unicode text exactly. Voice Input therefore:

1. puts the text on both the **clipboard** and the **primary selection**;
2. presses **Shift+Insert**: browsers, GTK and Qt applications and Electron paste the clipboard,
   while VTE terminals (GNOME Terminal, Ptyxis, Tilix) and xterm paste the primary selection —
   either way, the dictated text.

Key codes are layout-independent, so Shift+Insert works whatever layout is active.

## Why X11 selections on GNOME under Wayland

On Wayland, a client may set the clipboard only while it has keyboard focus — unless the
compositor offers the data-control protocol, which wlroots compositors and KDE do but GNOME's
Mutter does not. `wl-copy` then maps a tiny window to obtain focus; from a background daemon
GNOME never gives it focus, and `wl-copy` waits forever.

X11 has no such rule: any client can own a selection. GNOME synchronises X11 selections with
Wayland ones, so a selection owned through XWayland is pasted by Wayland applications too. The
daemon therefore keeps one X connection on a dedicated thread, owns `CLIPBOARD` and `PRIMARY`, and
answers `TARGETS`, `UTF8_STRING`, `STRING`, `TEXT` and `text/plain` requests until another program
takes the selection over. On X11 sessions the same code is used, so no `xclip` is needed.

## Why uinput

The paste keys must reach whatever window has focus. On Wayland, only the compositor can inject
input into other applications, and GNOME exposes no unprivileged protocol for it (the remote
desktop portal asks for permission and shows a sharing indicator). A kernel virtual keyboard
(`/dev/uinput`) looks like a real keyboard to every compositor and to X11. Access is granted with a
udev `uaccess` tag, which systemd-logind turns into an ACL for the user at the active seat — a
narrower permission than joining the `input` group, which would also allow reading all keyboards.

The device is created once when the daemon starts and kept, because compositors need a moment to
register a new keyboard before they accept its keys.

## Language detection

With `--lang auto`, Whisper detects the language from the audio. If it picks a language outside
English, Russian and Hebrew (Hebrew is sometimes heard as Yiddish, Russian as Ukrainian), the
audio is recognised again in the most probable supported language. When the detected language has
its own model in `[models]`, that model does the recognition.

## Daemon protocol (v1)

One request per connection: a single line of JSON in, a single line of JSON out.

```json
{"v": 1, "cmd": "toggle", "language": "ru"}
{"ok": true, "state": "recording", "message": "recording (RU)"}
```

| `cmd` | `language` | Effect |
|---|---|---|
| `ping` | — | `{"ok": true, "message": "pong", "pid": …, "version": …}` |
| `status` | — | State, recording time, model state, insertion method, … |
| `toggle` | optional | Start (idle) or stop and type (recording); `busy` while transcribing. |
| `start` | optional | Start recording. |
| `stop` | — | Stop and type. |
| `cancel` | — | Discard the recording, or the result still being recognised. |
| `shutdown` | — | Stop the daemon. |

`language` is `en`, `ru`, `he` or `auto`; without it the configured `language` applies. Errors
are `{"ok": false, "message": "…"}`. The socket is mode 0600 in a 0700 directory, and a `flock` on
`daemon.lock` guarantees a single daemon; a socket file left by a crashed daemon is replaced.

## Threads in the daemon

- main: waits for a signal or `shutdown`;
- `voice-input-ipc`: the socket server (one short-lived thread per request);
- `voice-input-worker`: recognition and typing of one dictation;
- `voice-input-load`: preloading the model at start;
- `voice-input-x11-selection`: the X connection that owns the selections;
- `voice-input-notify`: sends notifications in order without blocking;
- PortAudio's callback thread, and `voice-input-limit` when the maximum duration is reached.

The controller's state is protected by a lock. A `cancel` while transcribing bumps a generation
counter, so the late result is discarded.

## Testing

- Unit tests use fakes for every collaborator: recorder, transcriber, inserter, feedback,
  `gsettings`, `systemctl`, the uinput kernel interface and external commands.
- `tests/test_daemon.py` runs the real daemon and CLI over a real socket with fake audio and model.
- `tests/test_xselection.py` exercises the X11 selection owner against a real X server; it runs
  when `VOICE_INPUT_TEST_X11=1` (CI uses Xvfb), because it replaces the clipboard.
- `tests/test_model_integration.py` recognises real speech with a real model when
  `VOICE_INPUT_TEST_SAMPLES` points to recordings.
