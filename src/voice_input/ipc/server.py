"""The daemon's Unix socket server.

The socket lives in a private runtime directory (mode 0700) and is itself mode 0600, so only
the user who runs the daemon can connect. A lock file makes sure only one daemon runs.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import socket
import socketserver
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from voice_input.ipc.protocol import (
    MAX_MESSAGE_BYTES,
    ProtocolError,
    Request,
    decode_request,
    encode_response,
    error_response,
)
from voice_input.paths import ensure_private_dir

_log = logging.getLogger(__name__)

Handler = Callable[[Request], dict[str, Any]]


class AlreadyRunningError(RuntimeError):
    pass


class InstanceLock:
    """An exclusive ``flock`` held for the daemon's lifetime."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        ensure_private_dir(self._path.parent)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise AlreadyRunningError("another voice-input daemon is already running") from None
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


class _RequestHandler(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        self.connection.settimeout(5.0)
        try:
            line = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
        except OSError:
            return
        if len(line) > MAX_MESSAGE_BYTES:
            response = error_response("request too large")
        else:
            try:
                response = self.server.handler(decode_request(line))
            except ProtocolError as exc:
                response = error_response(str(exc))
            except Exception as exc:
                _log.exception("request failed")
                response = error_response(f"internal error: {exc}")
        with contextlib.suppress(OSError):
            self.wfile.write(encode_response(response))


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, path: Path, handler: Handler) -> None:
        self.handler = handler
        super().__init__(str(path), _RequestHandler)


class CommandServer:
    def __init__(self, socket_path: Path, lock_path: Path, handler: Handler) -> None:
        self._socket_path = socket_path
        self._lock = InstanceLock(lock_path)
        self._handler = handler
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def start(self) -> None:
        self._lock.acquire()
        try:
            ensure_private_dir(self._socket_path.parent)
            # We hold the lock, so a socket file left here belongs to a dead daemon.
            with contextlib.suppress(FileNotFoundError):
                self._socket_path.unlink()
            old_umask = os.umask(0o177)
            try:
                self._server = _Server(self._socket_path, self._handler)
            finally:
                os.umask(old_umask)
            self._socket_path.chmod(0o600)
        except Exception:
            self._lock.release()
            raise
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="voice-input-ipc",
            daemon=True,
        )
        self._thread.start()
        _log.info("listening on %s", self._socket_path)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        with contextlib.suppress(FileNotFoundError):
            self._socket_path.unlink()
        self._lock.release()


def socket_is_live(path: Path, timeout: float = 0.5) -> bool:
    """True if something accepts connections on ``path``."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        try:
            probe.connect(str(path))
        except OSError:
            return False
    return True
