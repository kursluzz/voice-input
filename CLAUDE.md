# Voice Input — notes for AI coding sessions

Offline voice typing for Linux: a shortcut runs `voice-input toggle`, a daemon records, Whisper
(faster-whisper) recognises, and the text is pasted into the focused window.

## Status and planning

- Status lives in GitHub: milestones and issues at https://github.com/kursluzz/voice-input
  (`gh issue list`, `gh api repos/kursluzz/voice-input/milestones`). Start a session by reading
  the open issues of the current milestone; close issues with `Closes #N` in commits.
- Issues labelled `help wanted from maintainer` need a human (sudo, real microphone, screen
  recording). Do not try to work around them.

## Commands

```bash
uv sync
uv run pytest                     # must stay fast and need no hardware
uv run ruff check . && uv run ruff format --check . && uv run mypy   # mypy is strict
VOICE_INPUT_TEST_X11=1 uv run pytest tests/test_xselection.py         # replaces the clipboard!
VOICE_INPUT_TEST_SAMPLES=<dir> uv run pytest -m model                # real model
```

## Conventions

- Python 3.12–3.14, src layout, uv, `uv_build`. Ruff (line length 100) and mypy `--strict`.
- TDD: collaborators are injected (recorder, transcriber, inserter, feedback, command runners,
  ioctl/os functions) and tested with fakes; see `tests/fakes.py`.
- Never log dictated text. Log lengths, languages and timings via `extra=`.
- Conventional Commits; update `CHANGELOG.md` `[Unreleased]` and docs for user-visible changes.
- Not on PyPI: documentation installs from the GitHub URL.

## Platform facts that shaped the design (verified on Ubuntu 26.04, GNOME, Wayland)

- `wl-copy`/`wl-paste` hang when run from a background process on GNOME (no data-control
  protocol, they wait for keyboard focus). The clipboard is therefore owned through XWayland with
  python-xlib (`insert/xselection.py`); GNOME bridges it to Wayland.
- Text is pasted (Shift+Insert, with both CLIPBOARD and PRIMARY set) rather than typed, because
  virtual key codes depend on the active layout (Cyrillic/Hebrew).
- Keys are injected with a pure-Python `/dev/uinput` device; permission comes from a udev
  `uaccess` rule installed by `voice-input setup uinput`.
- PyAV 19 breaks `faster_whisper.decode_audio`; the project passes numpy arrays and reads WAV with
  the standard library.
- Default model `small` (int8, CPU): ~1.8 s for 6–8 s of speech on an i7-1165G7. `large-v3-turbo`
  ~6.7 s. See `docs/MODELS.md`.
