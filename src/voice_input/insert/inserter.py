"""Put text into the focused window: copy it, then press the paste keys.

Typing character by character is not used: virtual keyboards send key codes, and the
characters they produce depend on the active layout, so Russian or Hebrew text would come out
wrong. Pasting inserts any text exactly, in every layout.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import ClassVar, Protocol

from voice_input.config import Config, InsertMethod
from voice_input.controller import InsertResult
from voice_input.insert.clipboard import Clipboard, clipboard_for
from voice_input.insert.keys import KeyCombo, parse_combo
from voice_input.insert.uinput import UinputKeyboard, uinput_writable
from voice_input.system import (
    CommandFailedError,
    Runner,
    Session,
    Which,
    run,
    which,
)

_log = logging.getLogger(__name__)


class KeySender(Protocol):
    name: str

    def press(self, combo: KeyCombo) -> None: ...


class YdotoolKeyboard:
    """Keys through ``ydotool`` (needs the ``ydotoold`` daemon running)."""

    name = "ydotool"

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def press(self, combo: KeyCombo) -> None:
        events = [f"{code}:1" for code in combo.codes]
        events += [f"{code}:0" for code in reversed(combo.codes)]
        result = self._run(["ydotool", "key", *events])
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise CommandFailedError(f"ydotool failed ({detail}); is ydotoold running?")


class WtypeKeyboard:
    """Keys through ``wtype`` (wlroots compositors such as Sway and Hyprland; not GNOME)."""

    name = "wtype"
    _MODIFIERS: ClassVar[dict[str, str]] = {
        "shift": "shift",
        "ctrl": "ctrl",
        "alt": "alt",
        "super": "logo",
    }

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def press(self, combo: KeyCombo) -> None:
        *modifiers, key = combo.xkb_names()
        args = ["wtype"]
        for modifier in modifiers:
            args += ["-M", self._MODIFIERS.get(modifier, modifier)]
        args += ["-k", key]
        for modifier in reversed(modifiers):
            args += ["-m", self._MODIFIERS.get(modifier, modifier)]
        result = self._run(args)
        if result.returncode != 0:
            raise CommandFailedError(f"wtype failed: {result.stderr.strip()}")


class XdotoolKeyboard:
    """Keys through ``xdotool`` (X11 sessions)."""

    name = "xdotool"

    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def press(self, combo: KeyCombo) -> None:
        result = self._run(["xdotool", "key", "--clearmodifiers", "+".join(combo.xkb_names())])
        if result.returncode != 0:
            raise CommandFailedError(f"xdotool failed: {result.stderr.strip()}")


class PasteInserter:
    def __init__(
        self,
        clipboard: Clipboard,
        keyboard: KeySender | None,
        combo: KeyCombo,
        *,
        restore_clipboard: bool = False,
        settle_delay: float = 0.15,
        restore_delay: float = 0.6,
        sleep: Callable[[float], None] = time.sleep,
        in_background: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.clipboard = clipboard
        self.keyboard = keyboard
        self._combo = combo
        self._restore = restore_clipboard
        self._settle_delay = settle_delay
        self._restore_delay = restore_delay
        self._sleep = sleep
        self._in_background = in_background or _thread

    @property
    def method(self) -> str:
        return self.keyboard.name if self.keyboard is not None else InsertMethod.CLIPBOARD.value

    def insert(self, text: str) -> InsertResult:
        previous = self.clipboard.get_text() if self._restore and self.keyboard else None
        self.clipboard.set_text(text)
        if self.keyboard is None:
            return InsertResult(method=self.method, pasted=False)
        self._sleep(self._settle_delay)  # let the compositor see the new selection
        try:
            self.keyboard.press(self._combo)
        except Exception as exc:
            # The text is on the clipboard, so the user can still paste it by hand.
            _log.warning("automatic paste with %s failed: %s", self.keyboard.name, exc)
            raise PasteFailedError(str(exc)) from exc
        if previous is not None:
            self._in_background(lambda: self._put_back(previous))
        return InsertResult(method=self.method, pasted=True)

    def _put_back(self, previous: str) -> None:
        self._sleep(self._restore_delay)  # the application must read the selection first
        try:
            self.clipboard.set_text(previous)
        except Exception as exc:
            _log.warning("could not restore the clipboard: %s", exc)


class PasteFailedError(RuntimeError):
    """The text was copied, but the paste keys could not be sent."""

    def __str__(self) -> str:
        return f"copied to the clipboard, but pasting failed: {super().__str__()}"


def _thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="voice-input-restore", daemon=True).start()


def choose_method(
    requested: InsertMethod,
    session: Session,
    *,
    which: Which = which,
    uinput_ok: Callable[[], bool] = uinput_writable,
) -> InsertMethod:
    """The concrete insertion method for ``auto``; explicit choices are returned unchanged."""
    if requested is not InsertMethod.AUTO:
        return requested
    if session.kind == "x11" and which("xdotool"):
        return InsertMethod.XDOTOOL
    if uinput_ok():
        return InsertMethod.UINPUT
    if which("ydotool"):
        return InsertMethod.YDOTOOL
    if session.kind == "wayland" and which("wtype") and not (session.is_gnome or session.is_kde):
        return InsertMethod.WTYPE
    return InsertMethod.CLIPBOARD


def build_keyboard(method: InsertMethod, runner: Runner = run) -> KeySender | None:
    if method is InsertMethod.UINPUT:
        return UinputKeyboard()
    if method is InsertMethod.YDOTOOL:
        return YdotoolKeyboard(runner)
    if method is InsertMethod.WTYPE:
        return WtypeKeyboard(runner)
    if method is InsertMethod.XDOTOOL:
        return XdotoolKeyboard(runner)
    return None


def build_inserter(config: Config, session: Session, *, which: Which = which) -> PasteInserter:
    method = choose_method(config.insert_method, session, which=which)
    _log.info("text insertion: %s (session %s)", method.value, session.kind)
    return PasteInserter(
        clipboard_for(session, config.clipboard),
        build_keyboard(method),
        parse_combo(config.paste_keys),
        restore_clipboard=config.restore_clipboard,
    )
