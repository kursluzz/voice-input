from __future__ import annotations

import stat
from pathlib import Path

from voice_input import paths


def test_defaults_follow_home_when_xdg_is_unset() -> None:
    env = {"HOME": "/home/u"}
    assert paths.config_file(env) == Path("/home/u/.config/voice-input/config.toml")
    assert paths.log_dir(env) == Path("/home/u/.local/state/voice-input/logs")
    assert paths.socket_path(env) == Path("/home/u/.local/state/voice-input/run/daemon.sock")


def test_xdg_variables_are_used() -> None:
    env = {
        "HOME": "/home/u",
        "XDG_CONFIG_HOME": "/cfg",
        "XDG_STATE_HOME": "/state",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }
    assert paths.config_dir(env) == Path("/cfg/voice-input")
    assert paths.state_dir(env) == Path("/state/voice-input")
    assert paths.socket_path(env) == Path("/run/user/1000/voice-input/daemon.sock")
    assert paths.lock_path(env) == Path("/run/user/1000/voice-input/daemon.lock")


def test_relative_xdg_values_are_ignored() -> None:
    env = {"HOME": "/home/u", "XDG_CONFIG_HOME": "relative/cfg"}
    assert paths.config_dir(env) == Path("/home/u/.config/voice-input")


def test_ensure_private_dir_tightens_mode(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b"
    target.mkdir(parents=True, mode=0o755)
    paths.ensure_private_dir(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
