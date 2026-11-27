"""Real recognition with a downloaded Whisper model.

Runs only when ``VOICE_INPUT_TEST_SAMPLES`` names a directory with ``en.wav``, ``ru.wav``,
``he.wav`` and ``texts.json`` (``{"en": "...", "ru": "...", "he": "..."}``). Audio is not part
of the repository: record your own, or synthesise it with any text-to-speech voice. The model
is ``VOICE_INPUT_TEST_MODEL`` (default ``small``) and is downloaded on first use.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path

import pytest

from voice_input.audio.signal import read_wav
from voice_input.languages import Language
from voice_input.postprocess import clean_segments
from voice_input.stt.whisper import WhisperTranscriber

SAMPLES = os.environ.get("VOICE_INPUT_TEST_SAMPLES", "")
pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(not SAMPLES, reason="set VOICE_INPUT_TEST_SAMPLES to run"),
]


def similarity(a: str, b: str) -> float:
    def words(text: str) -> list[str]:
        return re.findall(r"\w+", text.casefold())

    return difflib.SequenceMatcher(None, words(a), words(b)).ratio()


@pytest.fixture(scope="module")
def transcriber() -> WhisperTranscriber:
    return WhisperTranscriber(model=os.environ.get("VOICE_INPUT_TEST_MODEL", "small"))


@pytest.fixture(scope="module")
def expected() -> dict[str, str]:
    data: dict[str, str] = json.loads((Path(SAMPLES) / "texts.json").read_text("utf-8"))
    return data


@pytest.mark.parametrize("language", list(Language))
def test_explicit_language(
    transcriber: WhisperTranscriber, expected: dict[str, str], language: Language
) -> None:
    audio = read_wav(Path(SAMPLES) / f"{language.value}.wav")
    result = transcriber.transcribe(audio, language)
    text = clean_segments(result.segments)
    assert result.language is language
    assert similarity(text, expected[language.value]) >= 0.75, text


@pytest.mark.parametrize("language", list(Language))
def test_auto_detection(
    transcriber: WhisperTranscriber, expected: dict[str, str], language: Language
) -> None:
    audio = read_wav(Path(SAMPLES) / f"{language.value}.wav")
    result = transcriber.transcribe(audio, None)
    assert result.language is language
    assert similarity(clean_segments(result.segments), expected[language.value]) >= 0.75
