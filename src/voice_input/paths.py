"""Locations of configuration, logs and the daemon socket, following the XDG base directories."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

APP_NAME: Final = "voice-input"
CONFIG_FILE_NAME: Final = "config.toml"
LOG_FILE_NAME: Final = "voice-input.log"
SOCKET_NAME: Final = "daemon.sock"
LOCK_NAME: Final = "daemon.lock"


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _xdg(environ: Mapping[str, str], variable: str, fallback: str) -> Path:
    value = environ.get(variable, "").strip()
    # The XDG specification says relative paths must be ignored.
    if value and Path(value).is_absolute():
        return Path(value)
    return Path(environ.get("HOME", str(Path.home()))) / fallback


def config_dir(environ: Mapping[str, str] | None = None) -> Path:
    return _xdg(_env(environ), "XDG_CONFIG_HOME", ".config") / APP_NAME


def config_file(environ: Mapping[str, str] | None = None) -> Path:
    return config_dir(environ) / CONFIG_FILE_NAME


def state_dir(environ: Mapping[str, str] | None = None) -> Path:
    return _xdg(_env(environ), "XDG_STATE_HOME", ".local/state") / APP_NAME


def log_dir(environ: Mapping[str, str] | None = None) -> Path:
    return state_dir(environ) / "logs"


def runtime_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Private directory for the socket. Falls back to the state directory without a runtime dir."""
    env = _env(environ)
    value = env.get("XDG_RUNTIME_DIR", "").strip()
    if value and Path(value).is_absolute():
        return Path(value) / APP_NAME
    return state_dir(env) / "run"


def socket_path(environ: Mapping[str, str] | None = None) -> Path:
    return runtime_dir(environ) / SOCKET_NAME


def lock_path(environ: Mapping[str, str] | None = None) -> Path:
    return runtime_dir(environ) / LOCK_NAME


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` (mode 0700) if needed and tighten its mode if it already exists."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path
