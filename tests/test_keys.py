from __future__ import annotations

import pytest

from voice_input.insert.keys import KEY_CODES, KeyCombo, parse_combo


def test_shift_insert() -> None:
    combo = parse_combo("shift+insert")
    assert combo == KeyCombo((42,), 110)
    assert combo.codes == (42, 110)
    assert combo.xkb_names() == ["shift", "Insert"]


def test_ctrl_shift_v_is_case_and_space_insensitive() -> None:
    combo = parse_combo(" Ctrl + Shift + V ")
    assert combo == KeyCombo((29, 42), 47)
    assert combo.xkb_names() == ["ctrl", "shift", "v"]


def test_letter_and_digit_codes_follow_the_keyboard() -> None:
    assert KEY_CODES["q"] == 16
    assert KEY_CODES["a"] == 30
    assert KEY_CODES["z"] == 44
    assert KEY_CODES["1"] == 2
    assert KEY_CODES["0"] == 11
    assert KEY_CODES["f1"] == 59
    assert KEY_CODES["f12"] == 88


@pytest.mark.parametrize("text", ["", "ctrl+", "ctrl+shift", "v+ctrl", "ctrl+nosuch", "a+b"])
def test_invalid_combinations(text: str) -> None:
    with pytest.raises(ValueError):
        parse_combo(text)
