# Changelog

All notable changes to Voice Input are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Releases are made with `bump-my-version`, which moves
the `[Unreleased]` entries below into a dated version section.

## [Unreleased]

## [0.2.0] - 2026-11-28

### Changed

- The default dictation shortcut is now **Super+Insert** instead of Super+T, which is free in
  GNOME. Run `voice-input setup shortcuts` after upgrading to move it.

### Added

- `voice-input setup shortcuts` refuses a shortcut that the paste keys would press again (for
  example Shift+Super+Insert with the default Shift+Insert paste).

## [0.1.0] - 2026-11-28

### Added

- Dictation into any focused field: press a shortcut, speak, press it again, and the text is
  pasted where the cursor is (browsers, editors, terminals, chat applications).
- Offline speech recognition with faster-whisper (Whisper `small`, int8 on the CPU by default;
  CUDA is used when available). Per-language model overrides, for example a Hebrew model.
- English, Russian and Hebrew, chosen by shortcut, plus automatic detection restricted to these
  three languages.
- Background daemon that keeps the model loaded and is started on demand by the first shortcut
  press; optional systemd user service to start it at login.
- Text insertion through the clipboard and primary selection plus a Shift+Insert key press from a
  virtual keyboard (uinput), with ydotool, wtype and xdotool alternatives and a clipboard-only
  fallback. On GNOME under Wayland the clipboard is held through XWayland, because `wl-copy` cannot
  set it from a background process there.
- `voice-input setup shortcuts|service|uinput|all` for GNOME shortcuts (Super+T, Shift+Super+E/R/H),
  the login service and the uinput permission (a udev `uaccess` rule).
- Notifications and sound cues for recording, recognising, typed text and errors.
- `voice-input doctor` to check the installation, `transcribe` for WAV files, `listen` for
  one-off dictation in a terminal, `devices`, `download` and `config`.
- Removal of phantom phrases Whisper produces on silence ("Субтитры сделал DimaTorzok",
  "Thanks for watching!").

[Unreleased]: https://github.com/kursluzz/voice-input/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kursluzz/voice-input/releases/tag/v0.1.0
