"""Short tones that tell the user recording started, stopped, or something went wrong."""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Final

import numpy as np

from voice_input.audio.signal import Samples

_log = logging.getLogger(__name__)

CUE_RATE: Final = 44_100


class Cue(StrEnum):
    START = "start"  # rising two notes
    STOP = "stop"  # falling two notes
    DONE = "done"  # one short high note
    ERROR = "error"  # one low note


_NOTES: Final[dict[Cue, tuple[tuple[float, float], ...]]] = {
    # (frequency in Hz, duration in seconds)
    Cue.START: ((660.0, 0.07), (990.0, 0.09)),
    Cue.STOP: ((990.0, 0.07), (660.0, 0.09)),
    Cue.DONE: ((1320.0, 0.06),),
    Cue.ERROR: ((220.0, 0.25),),
}


def _note(frequency: float, seconds: float, volume: float) -> Samples:
    t = np.arange(int(seconds * CUE_RATE), dtype=np.float32) / CUE_RATE
    tone = np.sin(2 * np.pi * frequency * t)
    fade = min(len(t) // 4, int(0.01 * CUE_RATE))  # 10 ms fades avoid clicks
    envelope = np.ones_like(t)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        envelope[:fade] = ramp
        envelope[-fade:] = ramp[::-1]
    return (tone * envelope * volume).astype(np.float32)


def render(cue: Cue, volume: float) -> Samples:
    gap = np.zeros(int(0.015 * CUE_RATE), dtype=np.float32)
    parts: list[Samples] = []
    for frequency, seconds in _NOTES[cue]:
        parts.extend([_note(frequency, seconds, volume), gap])
    return np.concatenate(parts)


Player = Callable[[Samples, int], None]


def _sounddevice_play(samples: Samples, rate: int) -> None:
    import sounddevice

    sounddevice.play(samples, rate, blocking=False)


class CuePlayer:
    """Plays cues without blocking. Failures are logged and otherwise ignored."""

    def __init__(self, *, enabled: bool, volume: float, player: Player | None = None) -> None:
        self._enabled = enabled and volume > 0
        self._volume = volume
        self._player: Player = player if player is not None else _sounddevice_play
        self._cache: dict[Cue, Samples] = {}

    def play(self, cue: Cue) -> None:
        if not self._enabled:
            return
        samples = self._cache.get(cue)
        if samples is None:
            samples = self._cache[cue] = render(cue, self._volume)
        try:
            self._player(samples, CUE_RATE)
        except Exception as exc:  # sound is a nicety; never let it break dictation
            _log.warning("cannot play the %s cue: %s", cue.value, exc)
