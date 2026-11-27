"""Reading and writing the clipboard and the primary selection.

Both selections receive the text. Shift+Insert then pastes it everywhere: browsers and most
toolkits paste the clipboard, while terminals built on VTE (GNOME Terminal, Ptyxis, Tilix) and
xterm paste the primary selection.

Two mechanisms exist. X11 selections (:mod:`voice_input.insert.xselection`) work on X11 and,
through XWayland, on GNOME. ``wl-copy`` works on Wayland compositors with the data-control
protocol (KDE, Sway, Hyprland); on GNOME it hangs when run from a background process.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from voice_input.config import ClipboardBackend
from voice_input.insert.xselection import XSelectionClipboard, x11_available
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
            result = self._run(["wl-paste", "--no-newline", "--type", "text/plain"], timeout=2.0)
        except (CommandNotFoundError, CommandFailedError):
            return None
        return result.stdout if result.returncode == 0 else None


def choose_backend(
    requested: ClipboardBackend,
    session: Session,
    *,
    x11_ok: Callable[[], bool] = x11_available,
) -> ClipboardBackend:
    if requested is not ClipboardBackend.AUTO:
        return requested
    if session.kind == "x11":
        return ClipboardBackend.X11
    if session.is_gnome and x11_ok():
        return ClipboardBackend.X11
    return ClipboardBackend.WL_CLIPBOARD


def clipboard_for(
    session: Session,
    requested: ClipboardBackend = ClipboardBackend.AUTO,
    *,
    runner: Runner = run,
    x11_ok: Callable[[], bool] = x11_available,
) -> Clipboard:
    backend = choose_backend(requested, session, x11_ok=x11_ok)
    if backend is ClipboardBackend.X11:
        return XSelectionClipboard()
    return WaylandClipboard(runner)
