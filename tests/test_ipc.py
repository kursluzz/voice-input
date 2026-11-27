from __future__ import annotations

import shutil
import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from voice_input.ipc.client import (
    DaemonNotRunningError,
    DaemonStartError,
    ensure_daemon,
    send,
)
from voice_input.ipc.protocol import (
    Command,
    ProtocolError,
    Request,
    decode_request,
    decode_response,
)
from voice_input.ipc.server import AlreadyRunningError, CommandServer, socket_is_live
from voice_input.languages import Language


@pytest.fixture
def short_dir() -> Iterator[Path]:
    # Unix socket paths are limited to about 100 bytes; pytest's tmp_path can be longer.
    path = Path(tempfile.mkdtemp(prefix="vi-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


# --- protocol ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_",
    [
        Request(Command.PING),
        Request(Command.TOGGLE),
        Request(Command.TOGGLE, Language.RU, use_default_language=False),
        Request(Command.START, None, use_default_language=False),
        Request(Command.STATUS),
    ],
)
def test_request_round_trip(request_: Request) -> None:
    assert decode_request(request_.encode()) == request_


def test_auto_language_is_explicit_on_the_wire() -> None:
    encoded = Request(Command.TOGGLE, None, use_default_language=False).encode()
    assert b'"language": "auto"' in encoded


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (b"not json\n", "malformed"),
        (b"[1]\n", "JSON object"),
        (b'{"v": 2, "cmd": "ping"}\n', "version"),
        (b'{"v": 1, "cmd": "explode"}\n', "unknown command"),
        (b'{"v": 1, "cmd": "status", "language": "ru"}\n', "does not take a language"),
        (b'{"v": 1, "cmd": "toggle", "language": 5}\n', "must be a string"),
        (b'{"v": 1, "cmd": "toggle", "language": "de"}\n', "unsupported language"),
        (b"\xff\n", "malformed"),
    ],
)
def test_bad_requests(line: bytes, message: str) -> None:
    with pytest.raises(ProtocolError, match=message):
        decode_request(line)


def test_decode_response_requires_ok() -> None:
    assert decode_response(b'{"ok": true, "message": "x"}\n')["ok"] is True
    with pytest.raises(ProtocolError):
        decode_response(b'{"message": "x"}\n')


# --- server and client ---------------------------------------------------------------------


def echo_handler(request: Request) -> dict[str, Any]:
    return {
        "ok": True,
        "message": request.command.value,
        "language": None if request.use_default_language else str(request.language),
    }


def start_server(directory: Path) -> CommandServer:
    server = CommandServer(directory / "run" / "d.sock", directory / "run" / "d.lock", echo_handler)
    server.start()
    return server


def test_client_server_round_trip(short_dir: Path) -> None:
    server = start_server(short_dir)
    try:
        reply = send(server.socket_path, Request(Command.TOGGLE, Language.HE, False))
        assert reply == {"ok": True, "message": "toggle", "language": "he"}
        reply = send(server.socket_path, Request(Command.STATUS))
        assert reply["language"] is None
    finally:
        server.stop()
    assert not server.socket_path.exists()


def test_socket_and_directory_are_private(short_dir: Path) -> None:
    server = start_server(short_dir)
    try:
        assert stat.S_IMODE(server.socket_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(server.socket_path.parent.stat().st_mode) == 0o700
    finally:
        server.stop()


def test_second_server_is_refused(short_dir: Path) -> None:
    server = start_server(short_dir)
    try:
        with pytest.raises(AlreadyRunningError):
            start_server(short_dir)
        assert socket_is_live(server.socket_path)  # the first one is untouched
    finally:
        server.stop()


def test_stale_socket_is_replaced(short_dir: Path) -> None:
    run = short_dir / "run"
    run.mkdir(mode=0o700)
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(run / "d.sock"))
    stale.close()  # leaves the file behind, as a crashed daemon would
    server = start_server(short_dir)
    try:
        assert send(server.socket_path, Request(Command.PING))["ok"]
    finally:
        server.stop()


def test_server_answers_bad_requests_with_an_error(short_dir: Path) -> None:
    server = start_server(short_dir)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(str(server.socket_path))
            conn.sendall(b'{"v": 1, "cmd": "nope"}\n')
            reply = decode_response(conn.recv(4096))
        assert reply["ok"] is False
        assert "unknown command" in reply["message"]
    finally:
        server.stop()


def test_handler_exception_becomes_internal_error(short_dir: Path) -> None:
    def broken(request: Request) -> dict[str, Any]:
        raise RuntimeError("kaput")

    run = short_dir / "run"
    server = CommandServer(run / "d.sock", run / "d.lock", broken)
    server.start()
    try:
        reply = send(server.socket_path, Request(Command.PING))
        assert reply == {"ok": False, "message": "internal error: kaput"}
    finally:
        server.stop()


def test_send_without_daemon(short_dir: Path) -> None:
    with pytest.raises(DaemonNotRunningError):
        send(short_dir / "absent.sock", Request(Command.PING))
    assert not socket_is_live(short_dir / "absent.sock")


def test_ensure_daemon_does_nothing_when_running(short_dir: Path) -> None:
    server = start_server(short_dir)
    spawned: list[bool] = []
    try:
        started = ensure_daemon(server.socket_path, spawn=lambda: spawned.append(True))
    finally:
        server.stop()
    assert started is False
    assert spawned == []


def test_ensure_daemon_spawns_and_waits(short_dir: Path) -> None:
    servers: list[CommandServer] = []
    try:
        started = ensure_daemon(
            short_dir / "run" / "d.sock",
            spawn=lambda: servers.append(start_server(short_dir)),
            poll=0.01,
        )
        assert started is True
        assert len(servers) == 1
    finally:
        for server in servers:
            server.stop()


def test_ensure_daemon_gives_up(short_dir: Path) -> None:
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    with pytest.raises(DaemonStartError, match="did not start"):
        ensure_daemon(
            short_dir / "d.sock",
            spawn=lambda: None,
            wait_seconds=1.0,
            sleep=sleep,
            clock=lambda: now[0],
        )
