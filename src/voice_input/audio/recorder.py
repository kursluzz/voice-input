"""Microphone capture through PortAudio (the ``sounddevice`` package).

The stream is opened at 16 kHz mono. If the device refuses that rate, it is opened at its own
default rate and the audio is resampled when the recording stops.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

from voice_input.audio import SAMPLE_RATE
from voice_input.audio.signal import Samples, resample

_log = logging.getLogger(__name__)


class RecorderError(RuntimeError):
    """The microphone cannot be opened."""


def _sounddevice() -> Any:
    try:
        import sounddevice
    except OSError as exc:  # libportaudio2 missing
        raise RecorderError(
            f"PortAudio is not available ({exc}). Install it: sudo apt install libportaudio2"
        ) from None
    return sounddevice


def input_devices(sd: Any | None = None) -> list[tuple[int, str, bool]]:
    """``(index, name, is_default)`` for every device that can record."""
    sd = sd if sd is not None else _sounddevice()
    try:
        default_input = sd.default.device[0]
    except (AttributeError, IndexError, TypeError):
        default_input = None
    return [
        (index, str(device["name"]), index == default_input)
        for index, device in enumerate(sd.query_devices())
        if device.get("max_input_channels", 0) > 0
    ]


def resolve_device(spec: str | None, sd: Any | None = None) -> int | None:
    """Turn a configured device (index or part of its name) into an index. None = default."""
    if spec is None or not spec.strip():
        return None
    if spec.strip().isdigit():
        return int(spec)
    wanted = spec.strip().casefold()
    for index, name, _ in input_devices(sd):
        if wanted in name.casefold():
            return index
    raise RecorderError(f"no input device matches {spec!r}; see `voice-input devices`")


class Recording:
    """One running capture. Created by :meth:`SoundDeviceRecorder.start`."""

    def __init__(
        self,
        sd: Any,
        device: int | None,
        max_seconds: float,
        on_limit: Callable[[], None],
    ) -> None:
        self._chunks: list[Samples] = []
        self._frames = 0
        self._limit_hit = False
        self._on_limit = on_limit
        self._lock = threading.Lock()
        self._stream, self._rate = self._open(sd, device)
        self._max_frames = int(max_seconds * self._rate)
        self._stream.start()

    def _open(self, sd: Any, device: int | None) -> tuple[Any, int]:
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=device,
                callback=self._callback,
            )
            return stream, SAMPLE_RATE
        except Exception as first_error:
            try:
                info = sd.query_devices(device, "input")
                rate = int(info["default_samplerate"])
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    device=device,
                    callback=self._callback,
                )
            except Exception as exc:
                raise RecorderError(f"cannot open the microphone: {exc}") from first_error
            _log.info("device does not take 16 kHz; recording at %d Hz and resampling", rate)
            return stream, rate

    def _callback(self, indata: Any, frames: int, _time: Any, status: Any) -> None:
        if status:
            _log.debug("input status: %s", status)
        with self._lock:
            if self._limit_hit:
                return
            self._chunks.append(np.array(indata[:, 0], dtype=np.float32))
            self._frames += frames
            if self._frames < self._max_frames:
                return
            self._limit_hit = True
        # Never stop the stream from its own callback: hand over to another thread.
        threading.Thread(target=self._on_limit, name="voice-input-limit", daemon=True).start()

    def _close(self) -> None:
        try:
            self._stream.stop()
        finally:
            self._stream.close()

    def stop(self) -> Samples:
        self._close()
        with self._lock:
            chunks = self._chunks
            self._chunks = []
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        return resample(audio, self._rate)

    def abort(self) -> None:
        self._close()
        with self._lock:
            self._chunks = []


class SoundDeviceRecorder:
    def __init__(
        self,
        *,
        device: str | None = None,
        max_seconds: float = 300.0,
        sd: Any | None = None,
    ) -> None:
        self._device_spec = device
        self._max_seconds = max_seconds
        self._sd = sd

    def start(self, on_limit: Callable[[], None]) -> Recording:
        sd = self._sd if self._sd is not None else _sounddevice()
        device = resolve_device(self._device_spec, sd)
        return Recording(sd, device, self._max_seconds, on_limit)
