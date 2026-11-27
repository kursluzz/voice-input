"""What the user sees and hears during a dictation: notifications and sound cues."""

from __future__ import annotations

from typing import Final

from voice_input.audio.cues import Cue, CuePlayer
from voice_input.controller import InsertResult, Transcript
from voice_input.desktop.notify import Notification, Notifier
from voice_input.languages import Language

PREVIEW_CHARS: Final = 120


def language_name(language: Language | None) -> str:
    return "auto-detect" if language is None else language.display_name


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class DesktopFeedback:
    def __init__(self, notifier: Notifier, cues: CuePlayer) -> None:
        self._notifier = notifier
        self._cues = cues

    def recording(self, language: Language | None) -> None:
        self._cues.play(Cue.START)
        self._notifier.show(
            Notification(
                f"Recording · {language_name(language)}",
                "Press the shortcut again to stop and type the text.",
            )
        )

    def transcribing(self, language: Language | None) -> None:
        self._cues.play(Cue.STOP)
        self._notifier.show(Notification(f"Recognising · {language_name(language)}…"))

    def inserted(self, text: str, transcript: Transcript, result: InsertResult) -> None:
        if result.pasted:
            title = f"Typed · {language_name(transcript.language)}"
            self._notifier.show(Notification(title, preview(text)))
            return
        self._cues.play(Cue.DONE)
        self._notifier.show(
            Notification(
                "Copied to the clipboard",
                "Paste it with Ctrl+V (Ctrl+Shift+V in a terminal).\n" + preview(text),
            )
        )

    def nothing_heard(self) -> None:
        self._notifier.show(
            Notification(
                "Nothing recognised",
                "Speak a little longer or closer to the microphone.",
            )
        )

    def cancelled(self) -> None:
        self._cues.play(Cue.STOP)
        self._notifier.show(Notification("Dictation cancelled"))

    def limit_reached(self) -> None:
        self._notifier.show(
            Notification("Maximum recording length reached", "Recognising what was recorded.")
        )

    def error(self, message: str) -> None:
        self._cues.play(Cue.ERROR)
        self._notifier.show(Notification("Voice Input: error", message, transient=False))
