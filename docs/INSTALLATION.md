# Installing, upgrading and removing Voice Input

Voice Input is installed straight from GitHub; it is not published on PyPI.

## Requirements

- Linux with a graphical session: GNOME on Wayland (tested on Ubuntu 26.04), another Wayland
  desktop, or X11.
- Python 3.12, 3.13 or 3.14. [uv](https://docs.astral.sh/uv/) downloads a suitable Python if the
  system one does not fit.
- System packages:

  ```bash
  sudo apt install libportaudio2 libnotify-bin
  ```

  `libportaudio2` is needed to record the microphone. `libnotify-bin` (`notify-send`) shows the
  notifications; without it dictation still works, with sound cues only.
- On GNOME under Wayland, XWayland must be available (it is by default): the clipboard is held
  through it. On other Wayland desktops install `wl-clipboard`.
- About 1 GB of disk for the default model and its runtime, and about 1 GB of free memory while the
  daemon runs.

## 1. Install the program

Choose one:

```bash
# uv (recommended): an isolated environment, the command lands in ~/.local/bin
uv tool install git+https://github.com/kursluzz/voice-input

# uv, pinned to a release tag (see https://github.com/kursluzz/voice-input/releases)
uv tool install git+https://github.com/kursluzz/voice-input@v0.2.0

# uv, from a release's wheel file
uv tool install "voice-input @ https://github.com/kursluzz/voice-input/releases/download/v0.2.0/voice_input-0.2.0-py3-none-any.whl"

# pipx
pipx install git+https://github.com/kursluzz/voice-input

# pip, inside a virtual environment you manage
python3 -m venv ~/.venvs/voice-input
~/.venvs/voice-input/bin/pip install git+https://github.com/kursluzz/voice-input
```

If `voice-input` is not found afterwards, `~/.local/bin` is not on your `PATH`: run
`uv tool update-shell` (or `pipx ensurepath`) and open a new terminal.

## 2. Set it up

```bash
voice-input setup all
```

This runs three independent steps, each of which you can also run alone and undo with `--remove`.
Add `--dry-run` to only print what would be done.

### Shortcuts — `voice-input setup shortcuts`

Adds GNOME custom shortcuts (Settings → Keyboard → Custom Shortcuts) that run
`voice-input toggle` with the right language. Existing shortcuts are kept; a binding already used
by GNOME or by another custom shortcut is reported. Change the keys in the
[configuration](CONFIGURATION.md#shortcuts) and run the command again.

On other desktops (KDE, XFCE, Sway, Hyprland …) create the shortcuts yourself, using the full path
from `which voice-input`:

| Key (suggested) | Command |
|---|---|
| Super+Insert | `/home/you/.local/bin/voice-input toggle` |
| Shift+Super+E | `/home/you/.local/bin/voice-input toggle --lang en` |
| Shift+Super+R | `/home/you/.local/bin/voice-input toggle --lang ru` |
| Shift+Super+H | `/home/you/.local/bin/voice-input toggle --lang he` |

For Sway, for example: `bindsym $mod+t exec voice-input toggle`.

### Login service — `voice-input setup service`

Installs `~/.config/systemd/user/voice-input.service` and starts it, so the model is already loaded
when you first press the shortcut. Without it, the first shortcut press starts the daemon (the
recording begins at once; recognition of the first dictation waits a second or two for the model).

```bash
systemctl --user status voice-input
journalctl --user -u voice-input
```

### Typing permission — `voice-input setup uinput`

To paste into the focused window, Voice Input presses Shift+Insert on a virtual keyboard created
through `/dev/uinput`. That device belongs to root, so this step installs, with `sudo`:

- `/etc/udev/rules.d/70-voice-input-uinput.rules`: tags `/dev/uinput` with `uaccess`, so
  systemd-logind gives the user at the active seat access to it. Nothing else changes: you are not
  added to the `input` group and cannot read other keyboards.
- `/etc/modules-load.d/voice-input-uinput.conf`: loads the `uinput` module at boot.

It then reloads udev, so no new login is needed. Check with `voice-input doctor` (the "typing" line).
Remove with `voice-input setup uinput --remove`.

Alternatives, if you prefer not to install the rule:

- `insert_method = "ydotool"` with a running `ydotoold`.
- `insert_method = "wtype"` on wlroots compositors (Sway, Hyprland); it does not work on GNOME/KDE.
- `insert_method = "xdotool"` on X11 (chosen automatically there when installed).
- `insert_method = "clipboard"`: only copy; you paste with Ctrl+V.

## 3. Download the model (optional)

```bash
voice-input download          # the configured model(s), by default "small" (~480 MB)
```

Models are stored in the Hugging Face cache (`~/.cache/huggingface/hub`) unless `model_dir` is
set. Without this step the first dictation downloads the model.

## Upgrade

```bash
voice-input --version              # what is installed now

uv tool upgrade voice-input        # to the latest commit on main (pipx: pipx upgrade voice-input)
# or, to be explicit about the source:
uv tool install --force git+https://github.com/kursluzz/voice-input
```

Then:

```bash
voice-input setup shortcuts             # picks up changed default keys, if a release changed them
systemctl --user restart voice-input    # without the login service: voice-input shutdown
voice-input doctor
```

The daemon must be restarted to run the new code; without the login service, `voice-input
shutdown` is enough (the next shortcut press starts it again). Your configuration, shortcuts and
models are kept. The [changelog](../CHANGELOG.md) lists what changed in each release.

### Install or switch to a specific version

Releases are git tags, listed on the [releases page](https://github.com/kursluzz/voice-input/releases).
Install one with `@<tag>`; `--force` replaces whatever version is installed, so the same command
upgrades, downgrades or switches back from `main`:

```bash
uv tool install --force git+https://github.com/kursluzz/voice-input@v0.2.0
pipx install --force git+https://github.com/kursluzz/voice-input@v0.2.0
```

A version installed from a tag stays on that tag: `uv tool upgrade` does not move it. To follow
`main` again, install without `@<tag>`. Afterwards, restart the daemon as above.

## Uninstall

```bash
voice-input setup all --remove     # shortcuts, service and udev rule (asks for sudo)
uv tool uninstall voice-input      # or: pipx uninstall voice-input
```

To remove data as well:

```bash
rm -r ~/.config/voice-input ~/.local/state/voice-input
# downloaded models (shared with other Hugging Face tools — remove only these):
rm -r ~/.cache/huggingface/hub/models--Systran--faster-whisper-*
```

## Where files live

| What | Location |
|---|---|
| Configuration | `~/.config/voice-input/config.toml` (`$XDG_CONFIG_HOME`, or `--config`, or `VOICE_INPUT_CONFIG`) |
| Log | `~/.local/state/voice-input/logs/voice-input.log` (rotated, 3 × 1 MB) |
| Daemon socket and lock | `$XDG_RUNTIME_DIR/voice-input/` (cleared at logout) |
| Models | `~/.cache/huggingface/hub/`, or `model_dir` |
| Login service | `~/.config/systemd/user/voice-input.service` |
| Shortcuts | GNOME settings (dconf), entries named `voice-input-*` |
| uinput rule | `/etc/udev/rules.d/70-voice-input-uinput.rules`, `/etc/modules-load.d/voice-input-uinput.conf` |
