"""Speech recognition with faster-whisper (CTranslate2).

Models are loaded lazily and kept in memory, one per model name. On first use a model is
downloaded from Hugging Face into its cache (or ``model_dir``); after that recognition is
fully offline.

Automatic detection lets Whisper guess the language. If it guesses a language Voice Input does
not support (Hebrew is sometimes taken for Yiddish or Arabic), the audio is recognised again in
the most probable supported language.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from voice_input.audio import SAMPLE_RATE
from voice_input.controller import Audio, Transcript
from voice_input.languages import SUPPORTED, Language

_log = logging.getLogger(__name__)


class SegmentLike(Protocol):
    text: str


class InfoLike(Protocol):
    language: str
    language_probability: float
    all_language_probs: Sequence[tuple[str, float]] | None


class WhisperModelLike(Protocol):
    def transcribe(
        self, audio: Audio, **options: Any
    ) -> tuple[Iterable[SegmentLike], InfoLike]: ...


@dataclass(frozen=True)
class ModelSettings:
    device: str = "auto"
    compute_type: str = "auto"
    cpu_threads: int = 0
    model_dir: Path | None = None


ModelFactory = Callable[[str, ModelSettings], WhisperModelLike]


def cuda_available() -> bool:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return False


def resolve_device(settings: ModelSettings) -> tuple[str, str]:
    """The concrete ``(device, compute_type)`` for ``auto`` values."""
    device = settings.device
    if device == "auto":
        device = "cuda" if cuda_available() else "cpu"
    compute_type = settings.compute_type
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


def load_faster_whisper(name: str, settings: ModelSettings) -> WhisperModelLike:
    from faster_whisper import WhisperModel

    device, compute_type = resolve_device(settings)
    root = str(settings.model_dir) if settings.model_dir else None
    _log.info("loading model %s on %s (%s)", name, device, compute_type)
    try:
        model: WhisperModelLike = WhisperModel(
            name,
            device=device,
            compute_type=compute_type,
            cpu_threads=settings.cpu_threads,
            download_root=root,
        )
        return model
    except Exception as exc:
        if device != "cuda" or settings.device == "cuda":
            raise
        # "auto" chose CUDA but its libraries are missing: CPU always works.
        _log.warning("CUDA failed (%s); falling back to the CPU", exc)
        fallback: WhisperModelLike = WhisperModel(
            name,
            device="cpu",
            compute_type="int8",
            cpu_threads=settings.cpu_threads,
            download_root=root,
        )
        return fallback


def is_model_cached(name: str, model_dir: Path | None = None) -> bool:
    """True if the model can be loaded without network access."""
    if Path(name).is_dir():
        return True
    try:
        from faster_whisper.utils import download_model

        download_model(name, local_files_only=True, cache_dir=str(model_dir) if model_dir else None)
    except Exception:
        return False
    return True


def download(name: str, model_dir: Path | None = None) -> Path:
    """Download a model (if needed) and return its local directory."""
    from faster_whisper.utils import download_model

    return Path(download_model(name, cache_dir=str(model_dir) if model_dir else None))


class WhisperTranscriber:
    def __init__(
        self,
        *,
        model: str,
        models: dict[Language, str] | None = None,
        settings: ModelSettings | None = None,
        beam_size: int = 5,
        vad_filter: bool = True,
        factory: ModelFactory = load_faster_whisper,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._default_model = model
        self._models = dict(models or {})
        self._settings = settings or ModelSettings()
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._factory = factory
        self._clock = clock
        self._loaded: dict[str, WhisperModelLike] = {}
        self._lock = threading.Lock()

    def model_name(self, language: Language | None) -> str:
        if language is not None and language in self._models:
            return self._models[language]
        return self._default_model

    @property
    def loaded_models(self) -> list[str]:
        with self._lock:
            return list(self._loaded)

    def _model(self, name: str) -> WhisperModelLike:
        with self._lock:
            model = self._loaded.get(name)
            if model is None:
                started = self._clock()
                model = self._loaded[name] = self._factory(name, self._settings)
                _log.info("model %s ready in %.1f s", name, self._clock() - started)
            return model

    def preload(self, language: Language | None = None) -> None:
        self._model(self.model_name(language))

    def _run(
        self, model: WhisperModelLike, audio: Audio, language: Language | None
    ) -> tuple[Iterable[SegmentLike], InfoLike]:
        return model.transcribe(
            audio,
            language=language.value if language else None,
            beam_size=self._beam_size,
            vad_filter=self._vad_filter,
            condition_on_previous_text=False,
        )

    def transcribe(self, audio: Audio, language: Language | None) -> Transcript:
        started = self._clock()
        model = self._model(self.model_name(language))
        segments, info = self._run(model, audio, language)
        if language is None:
            detected = choose_language(info)
            _log.info(
                "detected language",
                extra={"whisper": info.language, "chosen": detected.value},
            )
            if detected.value != info.language or self.model_name(detected) != self.model_name(
                None
            ):
                model = self._model(self.model_name(detected))
                segments, info = self._run(model, audio, detected)
            language = detected
        texts = tuple(segment.text for segment in segments)
        return Transcript(
            segments=texts,
            language=language,
            audio_seconds=len(audio) / SAMPLE_RATE,
            elapsed_seconds=self._clock() - started,
        )


def choose_language(info: InfoLike) -> Language:
    """Whisper's guess if supported, else the most probable supported language."""
    try:
        return Language(info.language)
    except ValueError:
        pass
    probabilities = dict(info.all_language_probs or ())
    if info.language == "yi":  # Whisper often hears Hebrew as Yiddish
        probabilities[Language.HE.value] = probabilities.get(Language.HE.value, 0.0) + 1.0
    best = max(SUPPORTED, key=lambda lang: probabilities.get(lang.value, 0.0))
    return best
