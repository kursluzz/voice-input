from __future__ import annotations

import pytest

from voice_input.postprocess import clean_segments, finish, is_phantom


@pytest.mark.parametrize(
    "segment",
    [
        "Субтитры сделал DimaTorzok",
        "Субтитры создавал DimaTorzok.",
        "Продолжение следует...",
        " Thanks for watching! ",
        "Thank you for watching.",
        "Subtitles by the Amara.org community",
        "תודה שצפיתם!",
    ],
)
def test_phantom_phrases_are_recognised(segment: str) -> None:
    assert is_phantom(segment)


@pytest.mark.parametrize(
    "segment",
    [
        "Thank you.",
        "Спасибо",
        "Thanks for watching the kids yesterday",
        "Продолжение следует после обеда",
        "",
    ],
)
def test_real_speech_is_kept(segment: str) -> None:
    assert not is_phantom(segment)


def test_clean_joins_segments_and_drops_phantoms() -> None:
    segments = [" Привет, это тест.", "  Второе   предложение ", "Субтитры сделал DimaTorzok"]
    assert clean_segments(segments) == "Привет, это тест. Второе предложение"


def test_clean_removes_space_before_punctuation() -> None:
    assert clean_segments(["Hello ,", "world !"]) == "Hello, world!"


def test_clean_of_nothing_is_empty() -> None:
    assert clean_segments([]) == ""
    assert clean_segments(["  ", "Thanks for watching!"]) == ""


def test_hebrew_text_is_untouched() -> None:
    assert clean_segments(["שלום, מה שלומך?"]) == "שלום, מה שלומך?"


def test_finish_adds_trailing_space_only_to_text() -> None:
    assert finish("Hi.", trailing_space=True) == "Hi. "
    assert finish("Hi.", trailing_space=False) == "Hi."
    assert finish("", trailing_space=True) == ""
