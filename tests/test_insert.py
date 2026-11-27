from __future__ import annotations

import os
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from voice_input.config import Config, InsertMethod
from voice_input.insert.clipboard import WaylandClipboard, X11Clipboard, clipboard_for
from voice_input.insert.inserter import (
    PasteFailedError,
    PasteInserter,
    WtypeKeyboard,
    XdotoolKeyboard,
    YdotoolKeyboard,
    build_inserter,
    build_keyboard,
    choose_method,
)
from voice_input.insert.keys import KeyCombo, parse_combo
from voice_input.insert.uinput import (
    EV_KEY,
    EV_SYN,
    UI_DEV_CREATE,
    UI_DEV_DESTROY,
    UI_DEV_SETUP,
    UI_SET_EVBIT,
    UI_SET_KEYBIT,
    UinputError,
    UinputKeyboard,
)
from voice_input.system import CommandFailedError, CommandNotFoundError, CommandResult, Session

SHIFT_INSERT = parse_combo("shift+insert")
GNOME = Session("wayland", "UBUNTU:GNOME")
SWAY = Session("wayland", "SWAY")
X11 = Session("x11", "XFCE")


@dataclass
class FakeRunner:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    missing: frozenset[str] = frozenset()
    calls: list[tuple[list[str], str | None, bool]] = field(default_factory=list)

    def __call__(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        capture: bool = True,
        timeout: float = 5.0,
    ) -> CommandResult:
        self.calls.append((list(args), input_text, capture))
        if args[0] in self.missing:
            raise CommandNotFoundError(args[0])
        return CommandResult(self.returncode, self.stdout, self.stderr)


# --- clipboard -----------------------------------------------------------------------------


def test_wayland_clipboard_sets_both_selections_without_capturing() -> None:
    runner = FakeRunner()
    WaylandClipboard(runner).set_text("Привет")
    assert runner.calls == [
        (["wl-copy", "--type", "text/plain;charset=utf-8"], "Привет", False),
        (["wl-copy", "--primary", "--type", "text/plain;charset=utf-8"], "Привет", False),
    ]


def test_wayland_clipboard_missing_tool_gives_install_hint() -> None:
    with pytest.raises(CommandNotFoundError, match="apt install wl-clipboard"):
        WaylandClipboard(FakeRunner(missing=frozenset({"wl-copy"}))).set_text("x")


def test_wayland_clipboard_failure() -> None:
    with pytest.raises(CommandFailedError, match="clipboard"):
        WaylandClipboard(FakeRunner(returncode=1)).set_text("x")


def test_wayland_clipboard_get() -> None:
    assert WaylandClipboard(FakeRunner(stdout="old")).get_text() == "old"
    assert WaylandClipboard(FakeRunner(returncode=1)).get_text() is None
    assert WaylandClipboard(FakeRunner(missing=frozenset({"wl-paste"}))).get_text() is None


def test_x11_clipboard() -> None:
    runner = FakeRunner(stdout="old")
    clipboard = X11Clipboard(runner)
    clipboard.set_text("שלום")
    assert [call[0][2] for call in runner.calls] == ["clipboard", "primary"]
    assert clipboard.get_text() == "old"
    with pytest.raises(CommandNotFoundError, match="apt install xclip"):
        X11Clipboard(FakeRunner(missing=frozenset({"xclip"}))).set_text("x")


def test_clipboard_for_session() -> None:
    assert isinstance(clipboard_for(GNOME), WaylandClipboard)
    assert isinstance(clipboard_for(X11), X11Clipboard)


# --- command keyboards ---------------------------------------------------------------------


def test_ydotool_presses_and_releases_in_order() -> None:
    runner = FakeRunner()
    YdotoolKeyboard(runner).press(parse_combo("ctrl+shift+v"))
    assert runner.calls[0][0] == ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]


def test_ydotool_failure_mentions_the_daemon() -> None:
    with pytest.raises(CommandFailedError, match="ydotoold"):
        YdotoolKeyboard(FakeRunner(returncode=1)).press(SHIFT_INSERT)


def test_wtype_arguments() -> None:
    runner = FakeRunner()
    WtypeKeyboard(runner).press(SHIFT_INSERT)
    assert runner.calls[0][0] == ["wtype", "-M", "shift", "-k", "Insert", "-m", "shift"]


def test_xdotool_arguments() -> None:
    runner = FakeRunner()
    XdotoolKeyboard(runner).press(parse_combo("ctrl+v"))
    assert runner.calls[0][0] == ["xdotool", "key", "--clearmodifiers", "ctrl+v"]


# --- uinput --------------------------------------------------------------------------------


class FakeKernel:
    def __init__(self, open_error: Exception | None = None) -> None:
        self.open_error = open_error
        self.ioctls: list[tuple[int, Any]] = []
        self.events: list[tuple[int, int, int]] = []
        self.closed: list[int] = []
        self.sleeps: list[float] = []

    def os_open(self, path: str, flags: int) -> int:
        if self.open_error is not None:
            raise self.open_error
        assert flags & os.O_WRONLY
        return 7

    def ioctl(self, fd: int, request: int, arg: Any) -> int:
        self.ioctls.append((request, arg))
        return 0

    def write(self, fd: int, data: bytes) -> int:
        _, _, kind, code, value = struct.unpack("llHHi", data)
        self.events.append((kind, code, value))
        return len(data)

    def keyboard(self) -> UinputKeyboard:
        return UinputKeyboard(
            Path("/dev/uinput"),
            os_open=self.os_open,
            ioctl=self.ioctl,
            write=self.write,
            close=self.closed.append,
            sleep=self.sleeps.append,
        )


def test_uinput_creates_device_once_and_sends_combo() -> None:
    kernel = FakeKernel()
    keyboard = kernel.keyboard()
    keyboard.press(SHIFT_INSERT)
    keyboard.press(SHIFT_INSERT)

    requests = [request for request, _ in kernel.ioctls]
    assert requests[0] == UI_SET_EVBIT
    assert requests.count(UI_DEV_CREATE) == 1
    assert requests.index(UI_DEV_SETUP) < requests.index(UI_DEV_CREATE)
    assert (UI_SET_KEYBIT, 110) in kernel.ioctls
    setup = next(arg for request, arg in kernel.ioctls if request == UI_DEV_SETUP)
    assert b"voice-input virtual keyboard" in setup

    keys = [(code, value) for kind, code, value in kernel.events if kind == EV_KEY]
    assert keys[:4] == [(42, 1), (110, 1), (110, 0), (42, 0)]
    assert len(keys) == 8
    syncs = [event for event in kernel.events if event[0] == EV_SYN]
    assert len(syncs) == len(keys)  # every key event is followed by a report
    assert kernel.sleeps[0] == pytest.approx(0.3)  # settle once after creation


def test_uinput_close_destroys_device() -> None:
    kernel = FakeKernel()
    keyboard = kernel.keyboard()
    keyboard.open()
    keyboard.close()
    keyboard.close()
    assert (UI_DEV_DESTROY, 0) in kernel.ioctls
    assert kernel.closed == [7]


def test_uinput_permission_error_explains_the_fix() -> None:
    keyboard = FakeKernel(open_error=PermissionError()).keyboard()
    with pytest.raises(UinputError, match="voice-input setup uinput"):
        keyboard.press(SHIFT_INSERT)


def test_uinput_missing_device_explains_modprobe() -> None:
    keyboard = FakeKernel(open_error=FileNotFoundError()).keyboard()
    with pytest.raises(UinputError, match="modprobe uinput"):
        keyboard.open()


# --- method choice -------------------------------------------------------------------------


def tools(*names: str) -> Any:
    return lambda program: f"/usr/bin/{program}" if program in names else None


@pytest.mark.parametrize(
    ("session", "available", "uinput", "expected"),
    [
        (GNOME, (), True, InsertMethod.UINPUT),
        (GNOME, ("ydotool",), False, InsertMethod.YDOTOOL),
        (GNOME, ("wtype",), False, InsertMethod.CLIPBOARD),  # wtype does not work on GNOME
        (SWAY, ("wtype",), False, InsertMethod.WTYPE),
        (X11, ("xdotool",), True, InsertMethod.XDOTOOL),
        (X11, (), True, InsertMethod.UINPUT),
        (X11, (), False, InsertMethod.CLIPBOARD),
    ],
)
def test_choose_method_auto(
    session: Session, available: tuple[str, ...], uinput: bool, expected: InsertMethod
) -> None:
    method = choose_method(
        InsertMethod.AUTO, session, which=tools(*available), uinput_ok=lambda: uinput
    )
    assert method is expected


def test_explicit_method_is_kept() -> None:
    assert choose_method(InsertMethod.WTYPE, GNOME, which=tools()) is InsertMethod.WTYPE


def test_build_keyboard() -> None:
    assert build_keyboard(InsertMethod.CLIPBOARD) is None
    assert isinstance(build_keyboard(InsertMethod.UINPUT), UinputKeyboard)
    assert isinstance(build_keyboard(InsertMethod.XDOTOOL), XdotoolKeyboard)


def test_build_inserter_from_config() -> None:
    config = Config(insert_method=InsertMethod.CLIPBOARD, paste_keys="ctrl+v")
    inserter = build_inserter(config, GNOME)
    assert inserter.method == "clipboard"
    assert isinstance(inserter.clipboard, WaylandClipboard)


# --- paste inserter ------------------------------------------------------------------------


@dataclass
class MemoryClipboard:
    text: str | None = "previous"
    history: list[str] = field(default_factory=list)
    name: str = "memory"

    def set_text(self, text: str) -> None:
        self.text = text
        self.history.append(text)

    def get_text(self) -> str | None:
        return self.text


@dataclass
class RecordingKeyboard:
    fail: Exception | None = None
    combos: list[KeyCombo] = field(default_factory=list)
    name: str = "fake-keys"

    def press(self, combo: KeyCombo) -> None:
        if self.fail:
            raise self.fail
        self.combos.append(combo)


def make_inserter(
    keyboard: RecordingKeyboard | None, clipboard: MemoryClipboard, restore: bool = False
) -> PasteInserter:
    return PasteInserter(
        clipboard,
        keyboard,
        SHIFT_INSERT,
        restore_clipboard=restore,
        sleep=lambda s: None,
        in_background=lambda work: work(),
    )


def test_paste_copies_then_presses_keys() -> None:
    clipboard, keyboard = MemoryClipboard(), RecordingKeyboard()
    result = make_inserter(keyboard, clipboard).insert("Привет ")
    assert clipboard.history == ["Привет "]
    assert keyboard.combos == [SHIFT_INSERT]
    assert result.pasted
    assert result.method == "fake-keys"


def test_clipboard_only_mode_does_not_press_keys() -> None:
    clipboard = MemoryClipboard()
    result = make_inserter(None, clipboard).insert("hi")
    assert clipboard.text == "hi"
    assert not result.pasted
    assert result.method == "clipboard"


def test_restore_puts_previous_text_back() -> None:
    clipboard = MemoryClipboard(text="keep me")
    make_inserter(RecordingKeyboard(), clipboard, restore=True).insert("dictated")
    assert clipboard.history == ["dictated", "keep me"]


def test_restore_skipped_when_clipboard_was_empty() -> None:
    clipboard = MemoryClipboard(text=None)
    make_inserter(RecordingKeyboard(), clipboard, restore=True).insert("dictated")
    assert clipboard.history == ["dictated"]


def test_key_failure_leaves_text_on_clipboard_and_says_so() -> None:
    clipboard = MemoryClipboard()
    keyboard = RecordingKeyboard(fail=UinputError("no permission"))
    with pytest.raises(PasteFailedError, match="copied to the clipboard, but pasting failed"):
        make_inserter(keyboard, clipboard).insert("text")
    assert clipboard.text == "text"
