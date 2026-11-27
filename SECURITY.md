# Security policy

Please report vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/kursluzz/voice-input/security/advisories/new),
not in a public issue. Expect an answer within a few days.

How Voice Input handles your data and privileges:

- **Offline.** Audio and text never leave the computer. The only network access is the download
  of Whisper models from Hugging Face, on first use or with `voice-input download`.
- **Audio** is recorded only between the start and stop of a dictation, kept in memory and
  discarded after recognition. It is never written to disk.
- **Text** is put on the clipboard and the primary selection so it can be pasted; like any
  copied text, other applications can read it there. It is not written to the log.
- **The daemon socket** is in `$XDG_RUNTIME_DIR/voice-input/` (directory 0700, socket 0600), so
  only your user can control the daemon. Any process running as your user can, however — treat
  your user account as the trust boundary.
- **uinput permission.** `voice-input setup uinput` installs a udev rule that gives the user at
  the active seat write access to `/dev/uinput` (through systemd-logind's `uaccess` ACL). Any
  program running as that user can then create virtual input devices and inject key presses. It
  does not grant reading other input devices. Remove it with `voice-input setup uinput --remove`,
  or use `insert_method = "clipboard"` if you do not want this.
- `setup uinput` is the only command that uses `sudo`; it prints every command before running it.
