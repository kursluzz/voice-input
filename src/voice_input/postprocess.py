"""Clean up Whisper output before it is typed.

Whisper was trained on subtitled video. On silence or noise it sometimes produces subtitle
credits or sign-off phrases that nobody said ("Субтитры сделал DimaTorzok", "Thanks for
watching!"). Segments that consist only of such a phrase are dropped. Whitespace is normalised.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final

# Compared after normalisation (lower case, punctuation and spaces removed), whole segment only.
_PHANTOM_PHRASES: Final = (
    # Russian
    "субтитры сделал dimatorzok",
    "субтитры создавал dimatorzok",
    "субтитры делал dimatorzok",
    "редактор субтитров асинецкая корректор аегорова",
    "продолжение следует",
    "спасибо за просмотр",
    "подписывайтесь на канал",
    "ставьте лайки и подписывайтесь на канал",
    # English
    "thanks for watching",
    "thank you for watching",
    "thank you for watching and see you next time",
    "please subscribe",
    "subtitles by the amaraorg community",
    "transcription by castingwords",
    # Hebrew
    "תודה שצפיתם",
    "כתוביות על ידי",
)

_NON_WORD: Final = re.compile(r"[\W_]+", re.UNICODE)
_SPACES: Final = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT: Final = re.compile(r"\s+([,.;:!?…])")


def _key(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _NON_WORD.sub(" ", folded).strip().replace(" ", "")


_PHANTOM_KEYS: Final = frozenset(_key(p) for p in _PHANTOM_PHRASES)


def is_phantom(segment: str) -> bool:
    """True if ``segment`` is only a known phantom phrase."""
    key = _key(segment)
    return bool(key) and key in _PHANTOM_KEYS


def clean_segments(segments: Iterable[str]) -> str:
    """Join recognised segments into one line of text, without phantom phrases."""
    kept = [s.strip() for s in segments if s.strip() and not is_phantom(s)]
    text = _SPACES.sub(" ", " ".join(kept)).strip()
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


def finish(text: str, *, trailing_space: bool) -> str:
    """Final form of the text to type: optionally followed by one space."""
    if not text:
        return ""
    return text + " " if trailing_space else text
