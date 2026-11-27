"""The background daemon: owns the microphone, the model and the virtual keyboard.

It answers the commands of :mod:`voice_input.ipc`. The socket is up within a moment of start,
so a shortcut can begin recording at once while the model loads in the background; the first
recognition waits for the model if it is not ready yet.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

from voice_input import __version__, paths
from voice_input.audio.cues import CuePlayer
from voice_input.audio.recorder import SoundDeviceRecorder
from voice_input.config import Config
from voice_input.controller import Controller
from voice_input.desktop.feedback import DesktopFeedback
from voice_input.desktop.notify import Notification, Notifier
from voice_input.insert.inserter import PasteInserter, build_inserter
from voice_input.insert.uinput import UinputKeyboard
from voice_input.ipc.protocol import Command, Request
from voice_input.ipc.server import CommandServer
from voice_input.stt.whisper import ModelSettings, WhisperTranscriber, is_model_cached
from voice_input.system import Session, detect_session

_log = logging.getLogger(__name__)


@dataclass
class Components:
    controller: Controller
    transcriber: WhisperTranscriber
    inserter: PasteInserter
    notifier: Notifier


def build_components(config: Config, session: Session) -> Components:
    notifier = Notifier(enabled=config.notifications)
    cues = CuePlayer(enabled=config.sound_cues, volume=config.cue_volume)
    transcriber = WhisperTranscriber(
        model=config.model,
        models=dict(config.models),
        settings=ModelSettings(
            device=config.device,
            compute_type=config.compute_type,
            cpu_threads=config.cpu_threads,
            model_dir=config.model_dir,
        ),
        beam_size=config.beam_size,
        vad_filter=config.vad_filter,
    )
    inserter = build_inserter(config, session)
    controller = Controller(
        recorder=SoundDeviceRecorder(
            device=config.input_device, max_seconds=config.max_recording_seconds
        ),
        transcriber=transcriber,
        inserter=inserter,
        feedback=DesktopFeedback(notifier, cues),
        min_seconds=config.min_recording_seconds,
        trailing_space=config.trailing_space,
    )
    return Components(controller, transcriber, inserter, notifier)


class Daemon:
    def __init__(
        self,
        config: Config,
        components: Components,
        *,
        session: Session,
        socket_path: Path,
        lock_path: Path,
    ) -> None:
        self.config = config
        self.components = components
        self.session = session
        self._stop = threading.Event()
        self._server = CommandServer(socket_path, lock_path, self.handle)
        self._model_state = "not loaded"

    # --- requests -----------------------------------------------------------------------

    def handle(self, request: Request) -> dict[str, Any]:
        controller = self.components.controller
        command = request.command
        if command is Command.PING:
            return {"ok": True, "message": "pong", "pid": os.getpid(), "version": __version__}
        if command is Command.STATUS:
            return {"ok": True, "message": "status", **controller.status(), **self.describe()}
        if command is Command.SHUTDOWN:
            self._stop.set()
            return {"ok": True, "message": "shutting down"}
        language = self.config.language if request.use_default_language else request.language
        if command is Command.TOGGLE:
            return controller.toggle(language).to_dict()
        if command is Command.START:
            return controller.start(language).to_dict()
        if command is Command.STOP:
            return controller.stop().to_dict()
        if command is Command.CANCEL:
            return controller.cancel().to_dict()
        raise AssertionError(f"unhandled command {command}")  # pragma: no cover

    def describe(self) -> dict[str, Any]:
        return {
            "pid": os.getpid(),
            "version": __version__,
            "session": self.session.kind,
            "insert_method": self.components.inserter.method,
            "default_language": self.config.language.value if self.config.language else "auto",
            "model": self.config.model,
            "model_state": self._model_state,
            "models_loaded": self.components.transcriber.loaded_models,
        }

    # --- lifecycle ----------------------------------------------------------------------

    def _preload(self) -> None:
        name = self.components.transcriber.model_name(self.config.language)
        if not is_model_cached(name, self.config.model_dir):
            self._model_state = "downloading"
            self.components.notifier.show(
                Notification(
                    "Downloading the speech model",
                    f"Model '{name}' is downloaded once; the first dictation waits for it.",
                )
            )
        else:
            self._model_state = "loading"
        try:
            self.components.transcriber.preload(self.config.language)
        except Exception as exc:
            self._model_state = f"failed: {exc}"
            _log.exception("cannot load the model %s", name)
            self.components.notifier.show(
                Notification("Voice Input: cannot load the model", str(exc), transient=False)
            )
            return
        self._model_state = "ready"

    def _prepare_keyboard(self) -> None:
        keyboard = self.components.inserter.keyboard
        if isinstance(keyboard, UinputKeyboard):
            try:
                keyboard.open()
            except Exception as exc:
                _log.warning("virtual keyboard unavailable: %s", exc)

    def request_stop(self, *_: object) -> None:
        self._stop.set()

    def run(self) -> None:
        self._server.start()
        _log.info(
            "daemon started",
            extra={"version": __version__, "session": self.session.kind, "pid": os.getpid()},
        )
        threading.Thread(
            target=self._prepare_keyboard, name="voice-input-keys", daemon=True
        ).start()
        if self.config.preload_model:
            threading.Thread(target=self._preload, name="voice-input-load", daemon=True).start()
        try:
            self._stop.wait()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        _log.info("daemon stopping")
        self.components.controller.cancel()
        self._server.stop()
        keyboard = self.components.inserter.keyboard
        if isinstance(keyboard, UinputKeyboard):
            keyboard.close()
        self.components.notifier.flush(timeout=1.0)


def run_daemon(config: Config) -> None:
    session = detect_session()
    daemon = Daemon(
        config,
        build_components(config, session),
        session=session,
        socket_path=paths.socket_path(),
        lock_path=paths.lock_path(),
    )

    def on_signal(signum: int, frame: FrameType | None) -> None:
        daemon.request_stop()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    daemon.run()
