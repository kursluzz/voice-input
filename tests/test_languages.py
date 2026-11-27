from __future__ import annotations

import pytest

from voice_input.languages import SUPPORTED, Language, language_label, parse_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("en", Language.EN),
        ("RU", Language.RU),
        (" he ", Language.HE),
        ("english", Language.EN),
        ("Russian", Language.RU),
        ("hebrew", Language.HE),
        ("iw", Language.HE),
        ("auto", None),
        ("AUTO", None),
    ],
)
def test_parse_language_accepts_codes_names_and_auto(text: str, expected: Language | None) -> None:
    assert parse_language(text) == expected


@pytest.mark.parametrize("text", ["de", "", "fr", "englisch"])
def test_parse_language_rejects_unsupported(text: str) -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        parse_language(text)


def test_supported_languages_are_exactly_the_three() -> None:
    assert {lang.value for lang in SUPPORTED} == {"en", "ru", "he"}


def test_only_hebrew_is_right_to_left() -> None:
    assert [lang for lang in SUPPORTED if lang.is_rtl] == [Language.HE]


def test_labels() -> None:
    assert language_label(None) == "AUTO"
    assert language_label(Language.RU) == "RU"
    assert Language.HE.display_name == "עברית"
