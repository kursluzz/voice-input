"""Talking to the daemon, and starting it when it is not running."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from voice_input.ipc.protocol import (
    MAX_MESSAGE_BYTES,
    Command,
    ProtocolError,
    Request,
    decode_response,
)

_log = logging.getLogger(__name__)


class DaemonNotRunningError(ConnectionError):
    pass


class DaemonStartError(RuntimeError):
    pass


def send(path: Path, request: Request, *, timeout: float = 5.0) -> dict[str, Any]:
    """Send one request and return the response. Raises :class:`DaemonNotRunningError`."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        try:
            conn.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError):
            raise DaemonNotRunningError("the voice-input daemon is not running") from None
        conn.sendall(request.encode())
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk
            if len(buffer) > MAX_MESSAGE_BYTES:
                raise ProtocolError("response too large")
    if not buffer:
        raise ProtocolError("the daemon closed the connection without answering")
    return decode_response(buffer)


def daemon_command() -> list[str]:
    return [sys.executable, "-m", "voice_input", "daemon"]


def spawn_daemon(command: Sequence[str] | None = None) -> None:
    """Start the daemon detached from this process (its own session, no terminal)."""
    subprocess.Popen(
        list(command or daemon_command()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env=os.environ.copy(),
    )


def ensure_daemon(
    path: Path,
    *,
    spawn: Callable[[], None] = spawn_daemon,
    wait_seconds: float = 15.0,
    poll: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Make sure a daemon answers on ``path``. Returns True if it had to be started."""
    try:
        send(path, Request(Command.PING), timeout=2.0)
        return False
    except DaemonNotRunningError:
        pass
    _log.info("starting the daemon")
    spawn()
    deadline = clock() + wait_seconds
    while clock() < deadline:
        sleep(poll)
        try:
            send(path, Request(Command.PING), timeout=2.0)
            return True
        except DaemonNotRunningError:
            continue
    raise DaemonStartError(
        f"the daemon did not start within {wait_seconds:g} s; "
        "run `voice-input daemon` in a terminal to see why"
    )
