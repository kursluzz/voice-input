"""Test doubles for the controller's collaborators."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from voice_input.audio import SAMPLE_RATE
from voice_input.controller import Audio, InsertResult, Transcript
from voice_input.languages import Language


def seconds_of_audio(seconds: float) -> Audio:
    return np.full(int(seconds * SAMPLE_RATE), 0.1, dtype=np.float32)


@dataclass
class FakeRecording:
    audio: Audio
    stopped: bool = False
    aborted: bool = False

    def stop(self) -> Audio:
        self.stopped = True
        return self.audio

    def abort(self) -> None:
        self.aborted = True


@dataclass
class FakeRecorder:
    seconds: float = 2.0
    fail: Exception | None = None
    recordings: list[FakeRecording] = field(default_factory=list)
    on_limit: Callable[[], None] | None = None

    def start(self, on_limit: Callable[[], None]) -> FakeRecording:
        if self.fail is not None:
            raise self.fail
        self.on_limit = on_limit
        recording = FakeRecording(seconds_of_audio(self.seconds))
        self.recordings.append(recording)
        return recording


@dataclass
class FakeTranscriber:
    segments: tuple[str, ...] = ("Hello world.",)
    detected: Language | None = Language.EN
    fail: Exception | None = None
    calls: list[tuple[int, Language | None]] = field(default_factory=list)

    def transcribe(self, audio: Audio, language: Language | None) -> Transcript:
        self.calls.append((len(audio), language))
        if self.fail is not None:
            raise self.fail
        return Transcript(
            segments=self.segments,
            language=language if language is not None else self.detected,
            audio_seconds=len(audio) / SAMPLE_RATE,
            elapsed_seconds=0.01,
        )


@dataclass
class FakeInserter:
    pasted: bool = True
    fail: Exception | None = None
    texts: list[str] = field(default_factory=list)

    def insert(self, text: str) -> InsertResult:
        if self.fail is not None:
            raise self.fail
        self.texts.append(text)
        return InsertResult(method="fake", pasted=self.pasted)


@dataclass
class FakeFeedback:
    events: list[tuple[str, object]] = field(default_factory=list)

    def recording(self, language: Language | None) -> None:
        self.events.append(("recording", language))

    def transcribing(self, language: Language | None) -> None:
        self.events.append(("transcribing", language))

    def inserted(self, text: str, transcript: Transcript, result: InsertResult) -> None:
        self.events.append(("inserted", text))

    def nothing_heard(self) -> None:
        self.events.append(("nothing_heard", None))

    def cancelled(self) -> None:
        self.events.append(("cancelled", None))

    def limit_reached(self) -> None:
        self.events.append(("limit_reached", None))

    def error(self, message: str) -> None:
        self.events.append(("error", message))

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.events]


class DeferredRunner:
    """Collects background work so a test decides when it runs."""

    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def __call__(self, work: Callable[[], None]) -> None:
        self.pending.append(work)

    def run_all(self) -> None:
        while self.pending:
            self.pending.pop(0)()
