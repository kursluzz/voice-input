"""Reading and writing the clipboard and the primary selection.

Both selections receive the text. Shift+Insert then pastes it everywhere: browsers and most
toolkits paste the clipboard, while terminals built on VTE (GNOME Terminal, Ptyxis, Tilix) and
xterm paste the primary selection.
"""

from __future__ import annotations

from typing import Protocol

from voice_input.system import CommandFailedError, CommandNotFoundError, Runner, Session, run


class Clipboard(Protocol):
    name: str

    def set_text(self, text: str) -> None: ...
    def get_text(self) -> str | None: ...


class WaylandClipboard:
    name = "wl-clipboard"
    _HINT = "Install it: sudo apt install wl-clipboard"

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def set_text(self, text: str) -> None:
        for extra in ([], ["--primary"]):
            try:
                result = self._run(
                    ["wl-copy", *extra, "--type", "text/plain;charset=utf-8"],
                    input_text=text,
                    capture=False,
                )
            except CommandNotFoundError:
                raise CommandNotFoundError("wl-copy", self._HINT) from None
            if result.returncode != 0:
                where = "primary selection" if extra else "clipboard"
                raise CommandFailedError(f"wl-copy could not set the {where}")

    def get_text(self) -> str | None:
        try:
            result = self._run(["wl-paste", "--no-newline", "--type", "text/plain"])
        except (CommandNotFoundError, CommandFailedError):
            return None
        return result.stdout if result.returncode == 0 else None


class X11Clipboard:
    name = "xclip"
    _HINT = "Install it: sudo apt install xclip"

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def set_text(self, text: str) -> None:
        for selection in ("clipboard", "primary"):
            try:
                result = self._run(
                    ["xclip", "-selection", selection, "-in"], input_text=text, capture=False
                )
            except CommandNotFoundError:
                raise CommandNotFoundError("xclip", self._HINT) from None
            if result.returncode != 0:
                raise CommandFailedError(f"xclip could not set the {selection} selection")

    def get_text(self) -> str | None:
        try:
            result = self._run(["xclip", "-selection", "clipboard", "-out"])
        except (CommandNotFoundError, CommandFailedError):
            return None
        return result.stdout if result.returncode == 0 else None


def clipboard_for(session: Session, runner: Runner = run) -> Clipboard:
    if session.kind == "x11":
        return X11Clipboard(runner)
    return WaylandClipboard(runner)
