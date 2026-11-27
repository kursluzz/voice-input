"""Microphone capture, WAV files and sound cues. All audio is mono float32 at 16 kHz."""

from __future__ import annotations

from typing import Final

SAMPLE_RATE: Final = 16_000
"""Whisper's native sample rate; everything inside Voice Input uses it."""
