"""X11 selections against a real X server.

These tests take over the clipboard of the display they run on, so they only run when
VOICE_INPUT_TEST_X11=1 is set. CI runs them under Xvfb.
"""

from __future__ import annotations

import os
import threading

import pytest

from voice_input.insert.xselection import SelectionError, XSelectionClipboard, x11_available

needs_x = pytest.mark.skipif(
    os.environ.get("VOICE_INPUT_TEST_X11") != "1" or not x11_available(),
    reason="set VOICE_INPUT_TEST_X11=1 and DISPLAY to run (it replaces the clipboard)",
)


def read_selection(name: str, target: str = "UTF8_STRING") -> str | None:
    """Read a selection the way another application would, on its own connection."""
    from Xlib import X, Xatom, display

    d = display.Display()
    try:
        window = d.screen().root.create_window(0, 0, 1, 1, 0, X.CopyFromParent)
        selection = Xatom.PRIMARY if name == "PRIMARY" else d.intern_atom(name)
        prop = d.intern_atom("TEST_OUT")
        window.convert_selection(selection, d.intern_atom(target), prop, X.CurrentTime)
        d.flush()
        result: list[str | None] = []

        def wait() -> None:
            while True:
                event = d.next_event()
                if event.type == X.SelectionNotify:
                    if event.property == X.NONE:
                        result.append(None)
                    else:
                        value = window.get_full_property(prop, X.AnyPropertyType).value
                        result.append(value.decode() if isinstance(value, bytes) else str(value))
                    return

        reader = threading.Thread(target=wait, daemon=True)
        reader.start()
        reader.join(3)
        return result[0] if result else None
    finally:
        d.close()


@needs_x
def test_other_clients_can_paste_both_selections() -> None:
    clipboard = XSelectionClipboard()
    try:
        clipboard.set_text("Привет, שלום, hello")
        assert read_selection("CLIPBOARD") == "Привет, שלום, hello"
        assert read_selection("PRIMARY") == "Привет, שלום, hello"
        assert read_selection("CLIPBOARD", "STRING") == "Привет, שלום, hello"
        assert read_selection("CLIPBOARD", "image/png") is None  # not offered
        clipboard.set_text("second")
        assert read_selection("CLIPBOARD") == "second"
        assert clipboard.get_text() == "second"
    finally:
        clipboard.close()


@needs_x
def test_get_text_reads_another_owner() -> None:
    first, second = XSelectionClipboard(), XSelectionClipboard()
    try:
        first.set_text("from the first")
        second.set_text("from the second")  # takes ownership away from the first
        assert first.get_text() == "from the second"
    finally:
        first.close()
        second.close()


def test_unreachable_display_is_reported() -> None:
    def opener(name: str | None) -> object:
        raise SelectionError("cannot connect to the X server")

    clipboard = XSelectionClipboard(opener=opener)
    with pytest.raises(SelectionError, match="cannot connect"):
        clipboard.set_text("x")
    assert clipboard.get_text() is None


def test_too_long_text_is_refused() -> None:
    with pytest.raises(SelectionError, match="too long"):
        XSelectionClipboard().set_text("x" * 300_000)


def test_x11_available_without_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    assert x11_available() is False
