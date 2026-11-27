"""Supported dictation languages.

Voice Input recognises English, Russian and Hebrew. A request can name one of them, or ask for
automatic detection, in which case Whisper's language guess is restricted to these three.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class Language(StrEnum):
    """A language the user can dictate in. Values are Whisper language codes."""

    EN = "en"
    RU = "ru"
    HE = "he"

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAMES[self]

    @property
    def is_rtl(self) -> bool:
        return self is Language.HE


AUTO: Final = "auto"
"""The word that selects automatic language detection."""

SUPPORTED: Final = tuple(Language)

_DISPLAY_NAMES: Final = {
    Language.EN: "English",
    Language.RU: "Русский",
    Language.HE: "עברית",
}

_ALIASES: Final = {
    "english": Language.EN,
    "eng": Language.EN,
    "russian": Language.RU,
    "rus": Language.RU,
    "hebrew": Language.HE,
    "heb": Language.HE,
    "iw": Language.HE,  # the old ISO 639-1 code for Hebrew
}


def parse_language(value: str) -> Language | None:
    """Parse a language name or code. Returns ``None`` for automatic detection.

    Raises ``ValueError`` for anything that is not ``auto`` or a supported language.
    """
    key = value.strip().lower()
    if key == AUTO:
        return None
    try:
        return Language(key)
    except ValueError:
        pass
    if key in _ALIASES:
        return _ALIASES[key]
    choices = ", ".join([AUTO, *SUPPORTED])
    raise ValueError(f"unsupported language {value!r}; choose one of: {choices}")


def language_label(language: Language | None) -> str:
    """Short label for notifications and status output, for example ``RU`` or ``AUTO``."""
    return AUTO.upper() if language is None else language.value.upper()
