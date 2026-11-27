# Configuration

Every setting is optional. Values come from, in increasing precedence:

1. built-in defaults,
2. the TOML file `~/.config/voice-input/config.toml` (`$XDG_CONFIG_HOME/voice-input/config.toml`;
   another file with `--config PATH` or `VOICE_INPUT_CONFIG=PATH`),
3. environment variables `VOICE_INPUT_<SETTING>` (for example `VOICE_INPUT_MODEL=base`),
4. command-line options (`--lang`, `--model`, `--log-level`).

`voice-input config` prints the effective values, `voice-input config --example` a commented file.
Unknown settings and invalid values are rejected with a message naming the setting (exit status 2).

The daemon reads the configuration when it starts. After a change, restart it:
`voice-input shutdown` (or `systemctl --user restart voice-input`).

## Recognition

| Setting | Default | Meaning |
|---|---|---|
| `language` | `"auto"` | Language of the default shortcut (Super+T): `auto`, `en`, `ru` or `he`. |
| `model` | `"small"` | Whisper model: `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`, `distil-large-v3`, a Hugging Face repository with a CTranslate2 model, or a local directory. See [MODELS.md](MODELS.md). |
| `[models]` | empty | Per-language models, for example `he = "ivrit-ai/whisper-large-v3-turbo-ct2"`. In `auto` mode the default model detects the language and the language's own model (if any) then recognises. |
| `device` | `"auto"` | `auto` (CUDA when available, else CPU), `cpu` or `cuda`. |
| `compute_type` | `"auto"` | CTranslate2 precision: `auto` is `int8` on the CPU and `float16` on CUDA. |
| `cpu_threads` | `0` | CPU threads for recognition; 0 lets CTranslate2 choose. |
| `beam_size` | `5` | Beam search width; 1 is a little faster and a little less accurate. |
| `vad_filter` | `true` | Remove silence before recognition (Silero VAD). Prevents invented text on silence. |
| `model_dir` | Hugging Face cache | Where models are downloaded. |
| `preload_model` | `true` | Load the default model when the daemon starts. |

## Recording

| Setting | Default | Meaning |
|---|---|---|
| `input_device` | system default | Microphone: part of its name or its index from `voice-input devices`. |
| `max_recording_seconds` | `300` | Recording stops and is recognised after this long. |
| `min_recording_seconds` | `0.3` | Shorter recordings (an accidental double press) are ignored. |

## Feedback

| Setting | Default | Meaning |
|---|---|---|
| `sound_cues` | `true` | Tones when recording starts and stops, and on errors. |
| `cue_volume` | `0.25` | 0.0 to 1.0. |
| `notifications` | `true` | Desktop notifications (needs `notify-send`). |

## Typing

| Setting | Default | Meaning |
|---|---|---|
| `insert_method` | `"auto"` | How the paste keys are pressed: `uinput`, `ydotool`, `wtype`, `xdotool`, or `clipboard` (copy only). `auto` picks xdotool on X11 when installed, then uinput when permitted, then ydotool, then wtype (not on GNOME/KDE), else `clipboard`. |
| `clipboard` | `"auto"` | Who holds the text: `x11` (X11 selections; on GNOME under Wayland through XWayland) or `wl-clipboard` (`wl-copy`, for KDE and wlroots compositors). `auto` uses `x11` on X11 and GNOME, `wl-clipboard` elsewhere. |
| `paste_keys` | `"shift+insert"` | The key combination that pastes. Shift+Insert works in browsers, editors and terminals. Alternatives: `ctrl+v`, `ctrl+shift+v`. |
| `restore_clipboard` | `false` | After pasting, put back the text that was on the clipboard before. |
| `trailing_space` | `true` | Add a space after the text, so consecutive dictations do not run together. |

## Shortcuts

Used by `voice-input setup shortcuts` (GNOME). Run it again after a change. An empty string
removes that shortcut. Bindings use GNOME's syntax: `<Super>`, `<Shift>`, `<Control>`, `<Alt>`
followed by a key name.

```toml
[shortcuts]
default = "<Super>t"        # toggle in the configured `language`
en = "<Shift><Super>e"
ru = "<Shift><Super>r"
he = "<Shift><Super>h"
cancel = ""                  # for example "<Shift><Super>t"
```

## Logging

| Setting | Default | Meaning |
|---|---|---|
| `log_level` | `"INFO"` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. The log never contains the dictated text. |

## Environment variables

Every setting except the `[models]` and `[shortcuts]` tables can be given as
`VOICE_INPUT_<NAME>` in upper case, for example:

```bash
VOICE_INPUT_LANGUAGE=he VOICE_INPUT_SOUND_CUES=off voice-input daemon
```

Booleans accept `true/false`, `yes/no`, `on/off` and `1/0`.
