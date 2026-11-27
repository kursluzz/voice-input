from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from tests.fakes import seconds_of_audio
from voice_input.controller import Audio
from voice_input.languages import Language
from voice_input.stt import whisper
from voice_input.stt.whisper import (
    ModelSettings,
    WhisperTranscriber,
    choose_language,
    resolve_device,
)


@dataclass
class Segment:
    text: str


@dataclass
class Info:
    language: str
    language_probability: float = 0.9
    all_language_probs: Sequence[tuple[str, float]] | None = None


class FakeModel:
    def __init__(self, name: str, script: dict[str | None, tuple[list[str], Info]]) -> None:
        self.name = name
        self.script = script
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: Audio, **options: Any) -> tuple[Iterable[Segment], Info]:
        self.calls.append(options)
        texts, info = self.script[options["language"]]
        return (Segment(t) for t in texts), info


class Factory:
    def __init__(self, script: dict[str | None, tuple[list[str], Info]]) -> None:
        self.script = script
        self.models: dict[str, FakeModel] = {}

    def __call__(self, name: str, settings: ModelSettings) -> FakeModel:
        assert name not in self.models, "a model must be loaded only once"
        self.models[name] = FakeModel(name, self.script)
        return self.models[name]


def make(factory: Factory, **kwargs: Any) -> WhisperTranscriber:
    return WhisperTranscriber(model="small", factory=factory, **kwargs)


def test_explicit_language_is_passed_through() -> None:
    factory = Factory({"ru": ([" Привет,", " мир."], Info("ru"))})
    transcriber = make(factory, beam_size=3, vad_filter=False)
    result = transcriber.transcribe(seconds_of_audio(2), Language.RU)
    assert result.segments == (" Привет,", " мир.")
    assert result.language is Language.RU
    assert result.audio_seconds == pytest.approx(2.0)
    call = factory.models["small"].calls[0]
    assert call["language"] == "ru"
    assert call["beam_size"] == 3
    assert call["vad_filter"] is False
    assert call["condition_on_previous_text"] is False


def test_auto_uses_whisper_guess_when_supported() -> None:
    factory = Factory({None: (["Hello"], Info("en"))})
    result = make(factory).transcribe(seconds_of_audio(1), None)
    assert result.language is Language.EN
    assert result.segments == ("Hello",)
    assert len(factory.models["small"].calls) == 1  # no second pass


def test_auto_retries_in_best_supported_language() -> None:
    probs = [("de", 0.5), ("ru", 0.3), ("en", 0.1), ("he", 0.05)]
    factory = Factory(
        {
            None: (["Hallo"], Info("de", all_language_probs=probs)),
            "ru": (["Привет"], Info("ru")),
        }
    )
    result = make(factory).transcribe(seconds_of_audio(1), None)
    assert result.language is Language.RU
    assert result.segments == ("Привет",)
    assert [c["language"] for c in factory.models["small"].calls] == [None, "ru"]


def test_auto_switches_to_the_per_language_model() -> None:
    factory = Factory({None: (["shalom"], Info("he")), "he": (["שלום"], Info("he"))})
    transcriber = make(factory, models={Language.HE: "ivrit"})
    result = transcriber.transcribe(seconds_of_audio(1), None)
    assert result.segments == ("שלום",)
    assert factory.models["ivrit"].calls[0]["language"] == "he"
    assert transcriber.loaded_models == ["small", "ivrit"]


def test_explicit_language_uses_its_model_only() -> None:
    factory = Factory({"he": (["שלום"], Info("he"))})
    transcriber = make(factory, models={Language.HE: "ivrit"})
    transcriber.transcribe(seconds_of_audio(1), Language.HE)
    assert list(factory.models) == ["ivrit"]


def test_models_are_cached_and_preloaded() -> None:
    factory = Factory({"en": (["a"], Info("en"))})
    transcriber = make(factory)
    transcriber.preload()
    transcriber.transcribe(seconds_of_audio(1), Language.EN)
    transcriber.transcribe(seconds_of_audio(1), Language.EN)
    assert list(factory.models) == ["small"]


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        (Info("he"), Language.HE),
        (Info("yi", all_language_probs=[("yi", 0.6), ("en", 0.3), ("he", 0.1)]), Language.HE),
        (Info("uk", all_language_probs=[("uk", 0.7), ("ru", 0.2), ("en", 0.1)]), Language.RU),
        (Info("xx", all_language_probs=None), Language.EN),
    ],
)
def test_choose_language(info: Info, expected: Language) -> None:
    assert choose_language(info) is expected


def test_resolve_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(whisper, "cuda_available", lambda: False)
    assert resolve_device(ModelSettings()) == ("cpu", "int8")
    monkeypatch.setattr(whisper, "cuda_available", lambda: True)
    assert resolve_device(ModelSettings()) == ("cuda", "float16")
    assert resolve_device(ModelSettings(device="cpu", compute_type="float32")) == (
        "cpu",
        "float32",
    )


def test_audio_type_is_float32() -> None:
    assert seconds_of_audio(0.1).dtype == np.float32
