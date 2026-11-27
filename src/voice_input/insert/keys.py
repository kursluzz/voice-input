"""Key combinations such as ``shift+insert``, as Linux input key codes.

The codes are those of ``linux/input-event-codes.h``. They identify physical keys, not
characters, so a combination works whatever keyboard layout is active.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Final

KEY_CODES: Final[dict[str, int]] = {
    "esc": 1,
    "escape": 1,
    "backspace": 14,
    "tab": 15,
    "enter": 28,
    "return": 28,
    "ctrl": 29,
    "control": 29,
    "leftctrl": 29,
    "shift": 42,
    "leftshift": 42,
    "alt": 56,
    "leftalt": 56,
    "space": 57,
    "rightctrl": 97,
    "rightshift": 54,
    "rightalt": 100,
    "altgr": 100,
    "home": 102,
    "up": 103,
    "pageup": 104,
    "left": 105,
    "right": 106,
    "end": 107,
    "down": 108,
    "pagedown": 109,
    "insert": 110,
    "delete": 111,
    "super": 125,
    "meta": 125,
    "leftmeta": 125,
}

# Letters and digits by their position on the keyboard (QWERTY scan codes).
_LETTER_ROWS: Final = {
    16: "qwertyuiop",
    30: "asdfghjkl",
    44: "zxcvbnm",
}
for _start, _row in _LETTER_ROWS.items():
    for _offset, _letter in enumerate(_row):
        KEY_CODES[_letter] = _start + _offset
for _offset, _digit in enumerate("1234567890"):
    KEY_CODES[_digit] = 2 + _offset
for _number in range(1, 11):
    KEY_CODES[f"f{_number}"] = 58 + _number  # F1 is 59 ... F10 is 68
KEY_CODES["f11"] = 87
KEY_CODES["f12"] = 88

MODIFIERS: Final = frozenset({29, 42, 56, 97, 54, 100, 125})

# Names that xdotool, wtype and similar tools use for the same keys.
XKB_NAMES: Final[dict[int, str]] = {
    1: "Escape",
    14: "BackSpace",
    15: "Tab",
    28: "Return",
    29: "ctrl",
    42: "shift",
    54: "shift",
    56: "alt",
    57: "space",
    97: "ctrl",
    100: "ISO_Level3_Shift",
    102: "Home",
    103: "Up",
    104: "Prior",
    105: "Left",
    106: "Right",
    107: "End",
    108: "Down",
    109: "Next",
    110: "Insert",
    111: "Delete",
    125: "super",
}
for _name, _code in KEY_CODES.items():
    if len(_name) == 1 and _name in string.ascii_lowercase + string.digits:
        XKB_NAMES[_code] = _name
    elif _name.startswith("f") and _name[1:].isdigit():
        XKB_NAMES[_code] = _name.upper()


@dataclass(frozen=True)
class KeyCombo:
    """Modifier keys held while one main key is pressed."""

    modifiers: tuple[int, ...]
    key: int

    @property
    def codes(self) -> tuple[int, ...]:
        return (*self.modifiers, self.key)

    def xkb_names(self) -> list[str]:
        return [XKB_NAMES[code] for code in self.codes]


def parse_combo(text: str) -> KeyCombo:
    """Parse ``"ctrl+shift+v"`` style text. Exactly one non-modifier key must come last."""
    names = [part.strip().lower() for part in text.split("+")]
    if not text.strip() or any(not name for name in names):
        raise ValueError(f"invalid key combination {text!r}")
    codes: list[int] = []
    for name in names:
        if name not in KEY_CODES:
            raise ValueError(f"unknown key {name!r} in {text!r}")
        codes.append(KEY_CODES[name])
    *modifiers, key = codes
    if key in MODIFIERS:
        raise ValueError(f"{text!r} must end with a key that is not a modifier")
    if any(code not in MODIFIERS for code in modifiers):
        raise ValueError(f"{text!r}: only modifiers may come before the last key")
    return KeyCombo(tuple(modifiers), key)
