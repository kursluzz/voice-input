from __future__ import annotations

import pytest

from tests.fakes import (
    DeferredRunner,
    FakeFeedback,
    FakeInserter,
    FakeRecorder,
    FakeTranscriber,
)
from voice_input.controller import Controller, State
from voice_input.languages import Language


class Rig:
    def __init__(self, **controller_args: object) -> None:
        self.recorder = FakeRecorder()
        self.transcriber = FakeTranscriber()
        self.inserter = FakeInserter()
        self.feedback = FakeFeedback()
        self.runner = DeferredRunner()
        self.now = 100.0
        self.controller = Controller(
            recorder=self.recorder,
            transcriber=self.transcriber,
            inserter=self.inserter,
            feedback=self.feedback,
            runner=self.runner,
            clock=lambda: self.now,
            **controller_args,  # type: ignore[arg-type]
        )


def state_of(rig: Rig) -> State:
    """Read the state through a call, so mypy does not narrow it between commands."""
    return rig.controller.state


@pytest.fixture
def rig() -> Rig:
    return Rig()


def test_toggle_twice_records_transcribes_and_inserts(rig: Rig) -> None:
    first = rig.controller.toggle(Language.RU)
    assert first.ok
    assert first.state is State.RECORDING
    assert state_of(rig) is State.RECORDING

    second = rig.controller.toggle(Language.EN)  # any shortcut stops; language set at start
    assert second.ok
    assert second.state is State.TRANSCRIBING
    assert rig.recorder.recordings[0].stopped

    rig.runner.run_all()
    assert state_of(rig) is State.IDLE
    assert rig.transcriber.calls == [(32_000, Language.RU)]
    assert rig.inserter.texts == ["Hello world. "]
    assert rig.feedback.names == ["recording", "transcribing", "inserted"]


def test_auto_language_is_passed_as_none(rig: Rig) -> None:
    rig.controller.toggle(None)
    rig.controller.toggle(None)
    rig.runner.run_all()
    assert rig.transcriber.calls[0][1] is None
    assert rig.controller.status()["last_language"] == "en"


def test_trailing_space_can_be_disabled() -> None:
    rig = Rig(trailing_space=False)
    rig.controller.toggle(Language.EN)
    rig.controller.toggle(Language.EN)
    rig.runner.run_all()
    assert rig.inserter.texts == ["Hello world."]


def test_toggle_while_transcribing_is_refused(rig: Rig) -> None:
    rig.controller.toggle(Language.EN)
    rig.controller.toggle(Language.EN)
    reply = rig.controller.toggle(Language.EN)
    assert not reply.ok
    assert reply.state is State.TRANSCRIBING
    assert "busy" in reply.message
    assert len(rig.recorder.recordings) == 1


def test_start_when_recording_is_refused(rig: Rig) -> None:
    rig.controller.start(Language.EN)
    reply = rig.controller.start(Language.RU)
    assert not reply.ok
    assert len(rig.recorder.recordings) == 1


def test_stop_when_idle_is_refused(rig: Rig) -> None:
    reply = rig.controller.stop()
    assert not reply.ok
    assert reply.state is State.IDLE


def test_too_short_recording_types_nothing() -> None:
    rig = Rig(min_seconds=0.5)
    rig.recorder.seconds = 0.2
    rig.controller.toggle(Language.EN)
    reply = rig.controller.toggle(Language.EN)
    assert reply.state is State.IDLE
    assert rig.runner.pending == []
    assert rig.transcriber.calls == []
    assert rig.feedback.names == ["recording", "nothing_heard"]


def test_empty_transcript_types_nothing(rig: Rig) -> None:
    rig.transcriber.segments = ("Субтитры сделал DimaTorzok",)
    rig.controller.toggle(Language.RU)
    rig.controller.toggle(Language.RU)
    rig.runner.run_all()
    assert rig.inserter.texts == []
    assert rig.feedback.names[-1] == "nothing_heard"
    assert state_of(rig) is State.IDLE


def test_cancel_while_recording_discards_audio(rig: Rig) -> None:
    rig.controller.toggle(Language.HE)
    reply = rig.controller.cancel()
    assert reply.ok
    assert state_of(rig) is State.IDLE
    assert rig.recorder.recordings[0].aborted
    assert rig.feedback.names == ["recording", "cancelled"]


def test_cancel_while_transcribing_discards_the_late_result(rig: Rig) -> None:
    rig.controller.toggle(Language.EN)
    rig.controller.toggle(Language.EN)
    rig.controller.cancel()
    assert state_of(rig) is State.IDLE

    # A new recording may start before the old recognition finishes.
    rig.controller.toggle(Language.RU)
    rig.runner.run_all()  # the old, cancelled work finishes now
    assert rig.inserter.texts == []
    assert state_of(rig) is State.RECORDING


def test_cancel_when_idle_is_harmless(rig: Rig) -> None:
    reply = rig.controller.cancel()
    assert reply.ok
    assert rig.feedback.events == []


def test_recorder_failure_is_reported_and_state_stays_idle(rig: Rig) -> None:
    rig.recorder.fail = OSError("no input device")
    reply = rig.controller.toggle(Language.EN)
    assert not reply.ok
    assert "no input device" in reply.message
    assert state_of(rig) is State.IDLE
    assert rig.feedback.events == [("error", "cannot start recording: no input device")]
    assert rig.controller.status()["last_error"] == "cannot start recording: no input device"


def test_transcriber_failure_returns_to_idle(rig: Rig) -> None:
    rig.transcriber.fail = RuntimeError("model missing")
    rig.controller.toggle(Language.EN)
    rig.controller.toggle(Language.EN)
    rig.runner.run_all()
    assert state_of(rig) is State.IDLE
    assert rig.feedback.events[-1] == ("error", "model missing")


def test_inserter_failure_returns_to_idle(rig: Rig) -> None:
    rig.inserter.fail = RuntimeError("wl-copy failed")
    rig.controller.toggle(Language.EN)
    rig.controller.toggle(Language.EN)
    rig.runner.run_all()
    assert state_of(rig) is State.IDLE
    assert rig.feedback.events[-1] == ("error", "wl-copy failed")


def test_limit_stops_and_transcribes(rig: Rig) -> None:
    rig.controller.toggle(Language.EN)
    assert rig.recorder.on_limit is not None
    rig.recorder.on_limit()
    assert state_of(rig) is State.TRANSCRIBING
    rig.runner.run_all()
    assert rig.inserter.texts == ["Hello world. "]
    assert rig.feedback.names == ["recording", "limit_reached", "transcribing", "inserted"]


def test_limit_after_manual_stop_is_ignored(rig: Rig) -> None:
    rig.controller.toggle(Language.EN)
    on_limit = rig.recorder.on_limit
    rig.controller.toggle(Language.EN)
    assert on_limit is not None
    on_limit()
    assert "limit_reached" not in rig.feedback.names


def test_status_while_recording(rig: Rig) -> None:
    assert rig.controller.status() == {"state": "idle"}
    rig.controller.toggle(Language.RU)
    rig.now += 2.5
    assert rig.controller.status() == {
        "state": "recording",
        "language": "ru",
        "recording_seconds": 2.5,
    }
    rig.controller.cancel()
    rig.controller.toggle(None)
    assert rig.controller.status()["language"] == "auto"


def test_reply_serialises() -> None:
    rig = Rig()
    assert rig.controller.toggle(Language.EN).to_dict() == {
        "ok": True,
        "state": "recording",
        "message": "recording (EN)",
    }
