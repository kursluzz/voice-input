"""Small signal helpers: resampling, down-mixing and WAV files (16-bit PCM)."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt

from voice_input.audio import SAMPLE_RATE

Samples = npt.NDArray[np.float32]


def to_mono(samples: npt.NDArray[np.floating]) -> Samples:
    """Average the channels of a ``(frames, channels)`` array; 1-D input is returned as is."""
    if samples.ndim == 1:
        return samples.astype(np.float32, copy=False)
    return samples.mean(axis=1).astype(np.float32)


def resample(samples: Samples, source_rate: int, target_rate: int = SAMPLE_RATE) -> Samples:
    """Resample mono audio. Good enough for speech recognition, not for music.

    Integer down-sampling ratios (48 kHz → 16 kHz) average each group of samples, which is
    a simple low-pass filter against aliasing. Other ratios use linear interpolation.
    """
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("sample rates must be positive")
    if source_rate == target_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    if source_rate % target_rate == 0:
        factor = source_rate // target_rate
        usable = samples.size - samples.size % factor
        return samples[:usable].reshape(-1, factor).mean(axis=1).astype(np.float32)
    count = round(samples.size * target_rate / source_rate)
    positions = np.linspace(0, samples.size - 1, count)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.float32)


def read_wav(path: Path) -> Samples:
    """Read a PCM WAV file (8, 16 or 32 bit, any rate, any channels) as mono 16 kHz float32."""
    with wave.open(str(path), "rb") as wav:
        width = wav.getsampwidth()
        channels = wav.getnchannels()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"{path}: unsupported sample width of {width} bytes")
    if channels > 1:
        data = to_mono(data.reshape(-1, channels))
    return resample(data, rate)


def write_wav(path: Path, samples: Samples, rate: int = SAMPLE_RATE) -> None:
    """Write mono float audio as 16-bit PCM."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
