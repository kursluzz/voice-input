from __future__ import annotations

from collections.abc import Sequence

from tests.test_insert import FakeRunner
from voice_input.audio.cues import Cue, CuePlayer
from voice_input.controller import InsertResult, Transcript
from voice_input.desktop.feedback import DesktopFeedback, preview
from voice_input.desktop.notify import Notification, Notifier
from voice_input.languages import Language
from voice_input.system import CommandNotFoundError, CommandResult


class SpyNotifier(Notifier):
    def __init__(self) -> None:
        super().__init__(enabled=True)
        self.shown: list[Notification] = []

    def show(self, notification: Notification) -> None:
        self.shown.append(notification)


class SpyCues(CuePlayer):
    def __init__(self) -> None:
        super().__init__(enabled=True, volume=0.1, player=lambda s, r: None)
        self.played: list[Cue] = []

    def play(self, cue: Cue) -> None:
        self.played.append(cue)


def make() -> tuple[DesktopFeedback, SpyNotifier, SpyCues]:
    notifier, cues = SpyNotifier(), SpyCues()
    return DesktopFeedback(notifier, cues), notifier, cues


TRANSCRIPT = Transcript(("Привет",), Language.RU, 1.0, 0.2)


def test_recording_plays_start_cue_and_names_the_language() -> None:
    feedback, notifier, cues = make()
    feedback.recording(Language.HE)
    feedback.recording(None)
    assert cues.played == [Cue.START, Cue.START]
    assert notifier.shown[0].summary == "Recording · עברית"
    assert notifier.shown[1].summary == "Recording · auto-detect"


def test_transcribing_plays_stop_cue() -> None:
    feedback, notifier, cues = make()
    feedback.transcribing(Language.RU)
    assert cues.played == [Cue.STOP]
    assert notifier.shown[0].summary.startswith("Recognising · Русский")


def test_pasted_text_is_previewed_silently() -> None:
    feedback, notifier, cues = make()
    feedback.inserted("Привет ", TRANSCRIPT, InsertResult("uinput", pasted=True))
    assert cues.played == []
    assert notifier.shown[0] == Notification("Typed · Русский", "Привет")


def test_clipboard_only_tells_the_user_to_paste() -> None:
    feedback, notifier, cues = make()
    feedback.inserted("Привет ", TRANSCRIPT, InsertResult("clipboard", pasted=False))
    assert cues.played == [Cue.DONE]
    assert notifier.shown[0].summary == "Copied to the clipboard"
    assert "Ctrl+V" in notifier.shown[0].body


def test_error_is_kept_in_the_notification_list() -> None:
    feedback, notifier, cues = make()
    feedback.error("boom")
    assert cues.played == [Cue.ERROR]
    assert notifier.shown[0].transient is False
    assert notifier.shown[0].body == "boom"


def test_other_events_notify() -> None:
    feedback, notifier, _ = make()
    feedback.nothing_heard()
    feedback.cancelled()
    feedback.limit_reached()
    assert [n.summary for n in notifier.shown] == [
        "Nothing recognised",
        "Dictation cancelled",
        "Maximum recording length reached",
    ]


def test_preview_truncates() -> None:
    assert preview("  short  ") == "short"
    long = "word " * 100
    assert len(preview(long, 20)) == 20
    assert preview(long, 20).endswith("…")


# --- notifier ------------------------------------------------------------------------------


def test_notifier_reuses_the_notification_id() -> None:
    runner = FakeRunner(stdout="42\n")
    notifier = Notifier(runner=runner)
    notifier.show(Notification("one"))
    notifier.show(Notification("two", "body", transient=False))
    notifier.flush()
    first, second = (call[0] for call in runner.calls)
    assert "--transient" in first
    assert not any(a.startswith("--replace-id") for a in first)
    assert "--replace-id=42" in second
    assert "--transient" not in second
    assert second[-3:] == ["--", "two", "body"]


def test_disabled_notifier_runs_nothing() -> None:
    runner = FakeRunner()
    notifier = Notifier(enabled=False, runner=runner)
    notifier.show(Notification("x"))
    notifier.flush()
    assert runner.calls == []


def test_missing_notify_send_is_tolerated() -> None:
    calls: list[Sequence[str]] = []

    def runner(args: Sequence[str], **_: object) -> CommandResult:
        calls.append(args)
        raise CommandNotFoundError("notify-send")

    notifier = Notifier(runner=runner)
    notifier.send_now(Notification("a"))
    notifier.send_now(Notification("b"))
    assert len(calls) == 2
