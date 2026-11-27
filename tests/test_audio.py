from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from voice_input.audio import SAMPLE_RATE
from voice_input.audio.cues import CUE_RATE, Cue, CuePlayer, render
from voice_input.audio.recorder import (
    RecorderError,
    SoundDeviceRecorder,
    input_devices,
    resolve_device,
)
from voice_input.audio.signal import read_wav, resample, to_mono, write_wav

# --- signal --------------------------------------------------------------------------------


def test_resample_integer_ratio_averages() -> None:
    samples = np.array([0, 3, 6, 3, 3, 3], dtype=np.float32)
    assert resample(samples, 48_000, 16_000).tolist() == [3.0, 3.0]


def test_resample_non_integer_ratio_keeps_duration() -> None:
    samples = np.linspace(0, 1, 44_100, dtype=np.float32)
    out = resample(samples, 44_100)
    assert out.size == SAMPLE_RATE
    assert out[0] == pytest.approx(0.0)
    assert out[-1] == pytest.approx(1.0)


def test_resample_same_rate_and_empty() -> None:
    samples = np.ones(10, dtype=np.float32)
    assert resample(samples, 16_000) is not None
    assert resample(np.zeros(0, dtype=np.float32), 48_000).size == 0
    with pytest.raises(ValueError):
        resample(samples, 0)


def test_to_mono() -> None:
    stereo = np.array([[1.0, 0.0], [0.5, 0.5]], dtype=np.float32)
    assert to_mono(stereo).tolist() == [0.5, 0.5]


def test_wav_round_trip(tmp_path: Path) -> None:
    samples = (np.sin(np.linspace(0, 100, SAMPLE_RATE)) * 0.5).astype(np.float32)
    path = tmp_path / "a.wav"
    write_wav(path, samples)
    loaded = read_wav(path)
    assert loaded.size == samples.size
    assert np.max(np.abs(loaded - samples)) < 1e-3


def test_read_wav_downmixes_and_resamples(tmp_path: Path) -> None:
    import wave

    path = tmp_path / "stereo.wav"
    frames = np.zeros((48_000, 2), dtype="<i2")
    frames[:, 0] = 16384
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48_000)
        wav.writeframes(frames.tobytes())
    loaded = read_wav(path)
    assert loaded.size == SAMPLE_RATE
    assert loaded.mean() == pytest.approx(0.25, abs=1e-3)


# --- recorder with a fake sounddevice ------------------------------------------------------


class FakeStream:
    def __init__(self, sd: FakeSoundDevice, samplerate: int, callback: Any, **_: Any) -> None:
        if samplerate not in sd.accepted_rates:
            raise RuntimeError(f"Invalid sample rate {samplerate}")
        self.samplerate = samplerate
        self.callback = callback
        self.started = False
        self.closed = False
        sd.streams.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True

    def feed(self, seconds: float, value: float = 0.1) -> None:
        frames = int(seconds * self.samplerate)
        self.callback(np.full((frames, 1), value, dtype=np.float32), frames, None, None)


class FakeSoundDevice:
    def __init__(self, accepted_rates: tuple[int, ...] = (16_000,)) -> None:
        self.accepted_rates = accepted_rates
        self.streams: list[FakeStream] = []
        self.default = type("Default", (), {"device": (1, 3)})()

    def InputStream(self, **kwargs: Any) -> FakeStream:  # noqa: N802 - mirrors sounddevice
        return FakeStream(self, **kwargs)

    def query_devices(self, device: Any = None, kind: str | None = None) -> Any:
        devices = [
            {"name": "HDMI output", "max_input_channels": 0, "default_samplerate": 48000.0},
            {"name": "Built-in Microphone", "max_input_channels": 2, "default_samplerate": 48000.0},
            {"name": "USB Headset Mic", "max_input_channels": 1, "default_samplerate": 48000.0},
        ]
        if kind == "input":
            return devices[1 if device is None else device]
        return devices


def test_input_devices_lists_only_inputs() -> None:
    assert input_devices(FakeSoundDevice()) == [
        (1, "Built-in Microphone", True),
        (2, "USB Headset Mic", False),
    ]


def test_resolve_device_by_index_name_or_default() -> None:
    sd = FakeSoundDevice()
    assert resolve_device(None, sd) is None
    assert resolve_device("  ", sd) is None
    assert resolve_device("2", sd) == 2
    assert resolve_device("usb", sd) == 2
    with pytest.raises(RecorderError, match="no input device matches"):
        resolve_device("bluetooth", sd)


def test_recording_collects_audio_at_16k() -> None:
    sd = FakeSoundDevice()
    recording = SoundDeviceRecorder(sd=sd).start(lambda: None)
    stream = sd.streams[0]
    assert stream.started
    stream.feed(0.5)
    stream.feed(0.25)
    audio = recording.stop()
    assert audio.dtype == np.float32
    assert audio.size == int(0.75 * SAMPLE_RATE)
    assert stream.closed


def test_recording_falls_back_to_device_rate_and_resamples() -> None:
    sd = FakeSoundDevice(accepted_rates=(48_000,))
    recording = SoundDeviceRecorder(sd=sd).start(lambda: None)
    stream = sd.streams[-1]
    assert stream.samplerate == 48_000
    stream.feed(1.0)
    assert recording.stop().size == SAMPLE_RATE


def test_recording_fails_cleanly_when_no_rate_works() -> None:
    sd = FakeSoundDevice(accepted_rates=())
    with pytest.raises(RecorderError, match="cannot open the microphone"):
        SoundDeviceRecorder(sd=sd).start(lambda: None)


def test_limit_calls_back_once_from_another_thread() -> None:
    sd = FakeSoundDevice()
    called = threading.Event()
    threads: list[str] = []

    def on_limit() -> None:
        threads.append(threading.current_thread().name)
        called.set()

    recording = SoundDeviceRecorder(sd=sd, max_seconds=1.0).start(on_limit)
    stream = sd.streams[0]
    stream.feed(0.6)
    assert not called.is_set()
    stream.feed(0.6)
    assert called.wait(2)
    stream.feed(0.6)  # ignored after the limit
    assert recording.stop().size == int(1.2 * SAMPLE_RATE)
    assert threads == ["voice-input-limit"]


def test_abort_discards_audio() -> None:
    sd = FakeSoundDevice()
    recording = SoundDeviceRecorder(sd=sd).start(lambda: None)
    sd.streams[0].feed(1.0)
    recording.abort()
    assert sd.streams[0].closed


# --- cues ----------------------------------------------------------------------------------


def test_render_respects_volume_and_has_no_clicks() -> None:
    samples = render(Cue.START, 0.5)
    assert samples.dtype == np.float32
    assert np.max(np.abs(samples)) <= 0.5 + 1e-6
    assert abs(samples[0]) < 0.01
    assert 0.15 < samples.size / CUE_RATE < 0.3


def test_cue_player_plays_and_caches() -> None:
    played: list[int] = []
    player = CuePlayer(enabled=True, volume=0.3, player=lambda s, rate: played.append(s.size))
    player.play(Cue.DONE)
    player.play(Cue.DONE)
    assert len(played) == 2
    assert played[0] == played[1]


def test_disabled_cue_player_is_silent() -> None:
    played: list[int] = []
    CuePlayer(enabled=False, volume=0.3, player=lambda s, r: played.append(1)).play(Cue.START)
    CuePlayer(enabled=True, volume=0.0, player=lambda s, r: played.append(1)).play(Cue.START)
    assert played == []


def test_cue_player_swallows_errors() -> None:
    def broken(samples: Any, rate: int) -> None:
        raise OSError("no output device")

    CuePlayer(enabled=True, volume=0.3, player=broken).play(Cue.ERROR)
