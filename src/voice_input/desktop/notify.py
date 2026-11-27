"""Desktop notifications through ``notify-send`` (libnotify), shown without blocking.

One notification is reused: each update replaces the previous one, so a dictation shows as a
single bubble that changes from "Recording" to "Recognising" to the result.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Final

from voice_input.system import CommandFailedError, CommandNotFoundError, Runner, run

_log = logging.getLogger(__name__)

APP_NAME: Final = "Voice Input"
ICON: Final = "audio-input-microphone"


@dataclass(frozen=True)
class Notification:
    summary: str
    body: str = ""
    urgency: str = "normal"  # low, normal or critical
    transient: bool = True  # not kept in the notification list


class Notifier:
    """Sends notifications in order on a worker thread. Never raises."""

    def __init__(self, *, enabled: bool = True, runner: Runner = run) -> None:
        self._enabled = enabled
        self._run = runner
        self._last_id: str | None = None
        self._queue: queue.Queue[Notification | threading.Event] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._missing_reported = False

    def show(self, notification: Notification) -> None:
        if not self._enabled:
            return
        with self._lock:
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._drain, name="voice-input-notify", daemon=True
                )
                self._worker.start()
        self._queue.put(notification)

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until queued notifications are sent (used by tests and at shutdown)."""
        if self._worker is None:
            return
        done = threading.Event()
        self._queue.put(done)
        done.wait(timeout)

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            if isinstance(item, threading.Event):
                item.set()
            else:
                self.send_now(item)

    def send_now(self, notification: Notification) -> None:
        args = [
            "notify-send",
            f"--app-name={APP_NAME}",
            f"--icon={ICON}",
            f"--urgency={notification.urgency}",
            "--print-id",
        ]
        if notification.transient:
            args.append("--transient")
        if self._last_id:
            args.append(f"--replace-id={self._last_id}")
        args += ["--", notification.summary, notification.body]
        try:
            result = self._run(args, timeout=3.0)
        except CommandNotFoundError:
            if not self._missing_reported:
                _log.warning("notify-send is missing; install libnotify-bin for notifications")
                self._missing_reported = True
            return
        except (CommandFailedError, OSError) as exc:
            _log.warning("notification failed: %s", exc)
            return
        printed = result.stdout.strip()
        if result.returncode == 0 and printed.isdigit():
            self._last_id = printed
