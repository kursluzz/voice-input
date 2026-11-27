"""The dictation state machine: idle → recording → transcribing → idle.

The controller owns no hardware. A recorder, a transcriber, an inserter and a feedback sink
are passed in, so the logic is tested with fakes. Commands return at once: recognition and
insertion run on a background worker, and the user hears and sees progress through feedback.

A shortcut is a toggle. The first press starts recording in the requested language, the next
press of any Voice Input shortcut stops it and types the text. While the previous recording is
still being recognised, a press is refused as busy.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from voice_input.audio import SAMPLE_RATE
from voice_input.languages import Language, language_label
from voice_input.postprocess import clean_segments, finish

_log = logging.getLogger(__name__)

Audio = npt.NDArray[np.float32]


class State(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class Recording(Protocol):
    def stop(self) -> Audio:
        """Stop capturing and return the mono 16 kHz samples."""
        ...

    def abort(self) -> None:
        """Stop capturing and discard the audio."""
        ...


class Recorder(Protocol):
    def start(self, on_limit: Callable[[], None]) -> Recording:
        """Start capturing. ``on_limit`` is called (from any thread) at the maximum duration."""
        ...


@dataclass(frozen=True)
class Transcript:
    segments: tuple[str, ...]
    language: Language | None
    audio_seconds: float
    elapsed_seconds: float


class Transcriber(Protocol):
    def transcribe(self, audio: Audio, language: Language | None) -> Transcript: ...


@dataclass(frozen=True)
class InsertResult:
    method: str
    pasted: bool  # False: the text is only on the clipboard and must be pasted by hand


class Inserter(Protocol):
    def insert(self, text: str) -> InsertResult: ...


class Feedback(Protocol):
    """What the user sees and hears. Implementations must not raise."""

    def recording(self, language: Language | None) -> None: ...
    def transcribing(self, language: Language | None) -> None: ...
    def inserted(self, text: str, transcript: Transcript, result: InsertResult) -> None: ...
    def nothing_heard(self) -> None: ...
    def cancelled(self) -> None: ...
    def limit_reached(self) -> None: ...
    def error(self, message: str) -> None: ...


@dataclass(frozen=True)
class Reply:
    ok: bool
    state: State
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "state": self.state.value, "message": self.message}


Runner = Callable[[Callable[[], None]], None]


def run_in_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="voice-input-worker", daemon=True).start()


class Controller:
    def __init__(
        self,
        *,
        recorder: Recorder,
        transcriber: Transcriber,
        inserter: Inserter,
        feedback: Feedback,
        min_seconds: float = 0.3,
        trailing_space: bool = True,
        runner: Runner = run_in_thread,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._recorder = recorder
        self._transcriber = transcriber
        self._inserter = inserter
        self._feedback = feedback
        self._min_seconds = min_seconds
        self._trailing_space = trailing_space
        self._runner = runner
        self._clock = clock
        self._lock = threading.RLock()
        self._state = State.IDLE
        self._recording: Recording | None = None
        self._language: Language | None = None
        self._started_at = 0.0
        self._generation = 0  # bumped by cancel, so a late result can be discarded
        self._last_error = ""
        self._last_language: Language | None = None

    # --- queries ------------------------------------------------------------------------

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    def status(self) -> dict[str, Any]:
        with self._lock:
            info: dict[str, Any] = {"state": self._state.value}
            if self._state is not State.IDLE:
                info["language"] = language_label(self._language).lower()
            if self._state is State.RECORDING:
                info["recording_seconds"] = round(self._clock() - self._started_at, 1)
            if self._last_language is not None:
                info["last_language"] = self._last_language.value
            if self._last_error:
                info["last_error"] = self._last_error
            return info

    # --- commands -----------------------------------------------------------------------

    def toggle(self, language: Language | None) -> Reply:
        state = self.state  # start() and stop() check the state again under the lock
        if state is State.IDLE:
            return self.start(language)
        if state is State.RECORDING:
            return self.stop()
        return Reply(False, state, "busy: still recognising the previous recording")

    def start(self, language: Language | None) -> Reply:
        with self._lock:
            if self._state is not State.IDLE:
                return Reply(False, self._state, f"cannot start: {self._state.value}")
            try:
                self._recording = self._recorder.start(self._on_limit)
            except Exception as exc:
                _log.exception("cannot start recording")
                return self._fail(f"cannot start recording: {exc}")
            self._state = State.RECORDING
            self._language = language
            self._started_at = self._clock()
            self._last_error = ""
        _log.info("recording started", extra={"language": language_label(language)})
        self._feedback.recording(language)
        return Reply(True, State.RECORDING, f"recording ({language_label(language)})")

    def stop(self) -> Reply:
        with self._lock:
            if self._state is not State.RECORDING or self._recording is None:
                return Reply(False, self._state, "not recording")
            recording, self._recording = self._recording, None
            try:
                audio = recording.stop()
            except Exception as exc:
                _log.exception("cannot stop recording")
                return self._fail(f"recording failed: {exc}")
            self._state = State.TRANSCRIBING
            language = self._language
            generation = self._generation
        seconds = len(audio) / SAMPLE_RATE
        _log.info("recording stopped", extra={"seconds": round(seconds, 2)})
        if seconds < self._min_seconds:
            self._finish(generation)
            self._feedback.nothing_heard()
            return Reply(True, State.IDLE, "recording too short; nothing typed")
        self._feedback.transcribing(language)
        self._runner(lambda: self._process(audio, language, generation))
        return Reply(True, State.TRANSCRIBING, "transcribing")

    def cancel(self) -> Reply:
        with self._lock:
            if self._state is State.RECORDING and self._recording is not None:
                recording, self._recording = self._recording, None
                self._state = State.IDLE
                self._generation += 1
                try:
                    recording.abort()
                except Exception:
                    _log.exception("error while aborting the recording")
            elif self._state is State.TRANSCRIBING:
                # Recognition cannot be interrupted; its result is thrown away instead.
                self._generation += 1
                self._state = State.IDLE
            else:
                return Reply(True, State.IDLE, "nothing to cancel")
        _log.info("cancelled")
        self._feedback.cancelled()
        return Reply(True, State.IDLE, "cancelled")

    # --- internals ----------------------------------------------------------------------

    def _on_limit(self) -> None:
        with self._lock:
            if self._state is not State.RECORDING:
                return
        _log.info("maximum recording duration reached")
        self._feedback.limit_reached()
        self.stop()

    def _fail(self, message: str) -> Reply:
        with self._lock:
            self._state = State.IDLE
            self._recording = None
            self._last_error = message
        self._feedback.error(message)
        return Reply(False, State.IDLE, message)

    def _finish(self, generation: int) -> bool:
        """Return to idle unless a cancel already did. True if this result still counts."""
        with self._lock:
            if generation != self._generation:
                return False
            self._state = State.IDLE
            return True

    def _process(self, audio: Audio, language: Language | None, generation: int) -> None:
        try:
            transcript = self._transcriber.transcribe(audio, language)
            text = finish(clean_segments(transcript.segments), trailing_space=self._trailing_space)
            _log.info(
                "recognised",
                extra={
                    "language": transcript.language.value if transcript.language else "?",
                    "chars": len(text),
                    "audio_s": round(transcript.audio_seconds, 2),
                    "elapsed_s": round(transcript.elapsed_seconds, 2),
                },
            )
            with self._lock:
                if generation != self._generation:
                    _log.info("result discarded after cancel")
                    return
                self._last_language = transcript.language
            if not text:
                self._finish(generation)
                self._feedback.nothing_heard()
                return
            result = self._inserter.insert(text)
            if self._finish(generation):
                self._feedback.inserted(text, transcript, result)
        except Exception as exc:
            _log.exception("recognition or insertion failed")
            with self._lock:
                if generation != self._generation:
                    return
                self._state = State.IDLE
                self._last_error = str(exc)
            self._feedback.error(str(exc))
