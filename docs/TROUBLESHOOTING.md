# Troubleshooting

Run `voice-input doctor` first: it checks the session, clipboard, typing permission, microphone,
models, notifications, the daemon and the shortcuts, and prints a fix for each problem.

To see what the daemon does, stop the background one and run it in a terminal:

```bash
voice-input shutdown            # or: systemctl --user stop voice-input
voice-input --log-level DEBUG daemon
```

Then use the shortcut, or `voice-input toggle` from another terminal. The log is also written to
`~/.local/state/voice-input/logs/voice-input.log`.

## Nothing happens when I press the shortcut

- Run `voice-input toggle` in a terminal. If that works, the shortcut is the problem: run
  `voice-input setup shortcuts` and look for "also used by" warnings, or check
  Settings → Keyboard → Custom Shortcuts.
- The shortcut uses the absolute path of the command. After moving the installation (for example
  from pipx to uv), run `voice-input setup shortcuts` again.

## The text is copied but not typed

The notification says "Copied to the clipboard". Voice Input could not press the paste keys:

- `voice-input doctor` shows the typing method. With `clipboard`, run `voice-input setup uinput`.
- If the rule is installed but access is still denied, log out and back in (the ACL is granted
  for the active session).
- "copied to the clipboard, but pasting failed" names the error of the key backend.

## The text is typed in the wrong place, or something else is pasted

- Paste goes to the window that has focus when recognition finishes. Do not switch windows
  between the second shortcut press and the text appearing.
- A terminal that pastes something else with Shift+Insert: set `paste_keys = "ctrl+shift+v"`.
- An application that ignores Shift+Insert: set `paste_keys = "ctrl+v"` (not in terminals).
- Keep the shortcut's modifier keys released after the second press: if Super is still held when
  the paste happens, the application receives Super+Shift+Insert.

## "Nothing recognised"

- Check the microphone: `voice-input devices`, then `voice-input listen` and speak.
- Choose the right microphone with `input_device` (part of its name).
- Very short recordings (under 0.3 s) are ignored on purpose.

## Wrong language, or mixed-up words

- Auto-detection needs a few words. Use the language's own shortcut for short phrases.
- A larger model is more accurate but slower; see [MODELS.md](MODELS.md). For Hebrew,
  `ivrit-ai/whisper-large-v3-turbo-ct2`, fine-tuned on Hebrew, is worth trying (slower on a CPU).

## The first dictation takes long

The model is downloaded (once) and loaded into memory. Run `voice-input download` in advance and
`voice-input setup service` to load the model at login.

## `wl-copy` hangs / clipboard errors on GNOME

GNOME does not let background programs use `wl-copy`. Keep `clipboard = "auto"` (X11 selections
through XWayland). `voice-input doctor` warns if `wl-clipboard` is forced on GNOME.

## "another voice-input daemon is already running"

Only one daemon runs per user. `voice-input status` shows its PID; stop it with
`voice-input shutdown`. With the login service installed, use `systemctl --user restart voice-input`
instead of starting a second one by hand.

## No sound cues or notifications

Install `libportaudio2` (sound) and `libnotify-bin` (notifications), or check that
`sound_cues` and `notifications` are not disabled.
