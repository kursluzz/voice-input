"""The daemon wired to fakes, driven through its handler and through the real socket and CLI."""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeFeedback, FakeRecorder
from tests.test_insert import MemoryClipboard, RecordingKeyboard
from voice_input import cli
from voice_input.config import Config
from voice_input.controller import Audio, Controller
from voice_input.daemon import Components, Daemon
from voice_input.desktop.notify import Notifier
from voice_input.insert.inserter import PasteInserter
from voice_input.insert.keys import parse_combo
from voice_input.ipc.protocol import Command, Request
from voice_input.languages import Language
from voice_input.stt.whisper import ModelSettings, WhisperTranscriber
from voice_input.system import Session


class Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class Info:
    def __init__(self, language: str) -> None:
        self.language = language
        self.language_probability = 1.0
        self.all_language_probs: Sequence[tuple[str, float]] | None = [(language, 1.0)]


class EchoModel:
    """Answers with the language it was asked for, so tests can see which one was used."""

    def transcribe(self, audio: Audio, **options: Any) -> tuple[Iterable[Segment], Info]:
        language = options["language"] or "en"
        return [Segment(f"text in {language}.")], Info(language)


def echo_factory(name: str, settings: ModelSettings) -> EchoModel:
    return EchoModel()


class Rig:
    def __init__(self, directory: Path, config: Config | None = None) -> None:
        self.config = config or Config(language=Language.RU, preload_model=False)
        self.clipboard = MemoryClipboard()
        self.keyboard = RecordingKeyboard()
        self.feedback = FakeFeedback()
        self.recorder = FakeRecorder()
        transcriber = WhisperTranscriber(model="fake", factory=echo_factory)
        inserter = PasteInserter(
            self.clipboard, self.keyboard, parse_combo("shift+insert"), sleep=lambda s: None
        )
        controller = Controller(
            recorder=self.recorder,
            transcriber=transcriber,
            inserter=inserter,
            feedback=self.feedback,
            runner=lambda work: work(),  # recognise synchronously
        )
        self.components = Components(controller, transcriber, inserter, Notifier(enabled=False))
        self.socket = directory / "run" / "daemon.sock"
        self.daemon = Daemon(
            self.config,
            self.components,
            session=Session("wayland", "GNOME"),
            socket_path=self.socket,
            lock_path=directory / "run" / "daemon.lock",
        )

    def handle(self, command: Command, language: str | None = None) -> dict[str, Any]:
        if language is None:
            return self.daemon.handle(Request(command))
        from voice_input.languages import parse_language

        return self.daemon.handle(Request(command, parse_language(language), False))


@pytest.fixture
def short_dir() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="vid-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_ping_and_status(short_dir: Path) -> None:
    rig = Rig(short_dir)
    assert rig.handle(Command.PING)["message"] == "pong"
    status = rig.handle(Command.STATUS)
    assert status["state"] == "idle"
    assert status["default_language"] == "ru"
    assert status["insert_method"] == "fake-keys"
    assert status["model_state"] == "not loaded"


def test_toggle_uses_configured_default_language(short_dir: Path) -> None:
    rig = Rig(short_dir)
    assert rig.handle(Command.TOGGLE)["state"] == "recording"
    rig.handle(Command.TOGGLE)
    assert rig.clipboard.text == "text in ru. "
    assert len(rig.keyboard.combos) == 1


def test_explicit_language_and_auto(short_dir: Path) -> None:
    rig = Rig(short_dir)
    rig.handle(Command.TOGGLE, "he")
    rig.handle(Command.TOGGLE)
    assert rig.clipboard.text == "text in he. "
    rig.handle(Command.START, "auto")
    rig.handle(Command.STOP)
    assert rig.clipboard.text == "text in en. "  # the echo model "detects" English


def test_cancel_and_shutdown(short_dir: Path) -> None:
    rig = Rig(short_dir)
    rig.handle(Command.START, "en")
    assert rig.handle(Command.CANCEL)["message"] == "cancelled"
    assert rig.clipboard.history == []
    assert rig.handle(Command.SHUTDOWN)["ok"] is True


def test_preload_marks_the_model_ready(short_dir: Path) -> None:
    rig = Rig(short_dir)
    rig.daemon._preload()
    status = rig.handle(Command.STATUS)
    assert status["model_state"] == "ready"
    assert status["models_loaded"] == ["fake"]


def test_preload_failure_is_reported(short_dir: Path) -> None:
    def broken(name: str, settings: ModelSettings) -> EchoModel:
        raise RuntimeError("no network")

    rig = Rig(short_dir)
    rig.components.transcriber._factory = broken
    rig.daemon._preload()
    assert rig.handle(Command.STATUS)["model_state"] == "failed: no network"


def test_cli_drives_the_running_daemon(
    short_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(short_dir / "config"))
    rig = Rig(short_dir / "voice-input")
    rig.socket = short_dir / "voice-input" / "daemon.sock"
    rig.daemon = Daemon(
        rig.config,
        rig.components,
        session=Session("wayland", "GNOME"),
        socket_path=rig.socket,
        lock_path=short_dir / "voice-input" / "daemon.lock",
    )
    thread = threading.Thread(target=rig.daemon.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not rig.socket.exists() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert cli.main(["toggle", "--lang", "en"]) == cli.EXIT_OK
    assert "recording (EN)" in capsys.readouterr().out
    assert cli.main(["status", "--json"]) == cli.EXIT_OK
    assert '"state": "recording"' in capsys.readouterr().out
    assert cli.main(["toggle", "--quiet"]) == cli.EXIT_OK
    assert capsys.readouterr().out == ""
    assert rig.clipboard.text == "text in en. "
    assert cli.main(["stop"]) == cli.EXIT_FAILED  # not recording any more
    assert "not recording" in capsys.readouterr().err

    assert cli.main(["shutdown"]) == cli.EXIT_OK
    thread.join(5)
    assert not thread.is_alive()
    assert not rig.socket.exists()


def test_cli_without_daemon(
    short_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(short_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(short_dir / "config"))
    assert cli.main(["stop"]) == cli.EXIT_NO_DAEMON
    assert cli.main(["toggle", "--no-autostart"]) == cli.EXIT_NO_DAEMON
    assert cli.main(["shutdown"]) == cli.EXIT_OK
    assert "not running" in capsys.readouterr().out
