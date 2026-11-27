"""A systemd user service that starts the daemon with the graphical session."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from voice_input.system import CommandFailedError, Runner, run

UNIT_NAME: Final = "voice-input.service"


def unit_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    config_home = env.get("XDG_CONFIG_HOME", "").strip()
    base = (
        Path(config_home)
        if config_home and Path(config_home).is_absolute()
        else Path(env.get("HOME", str(Path.home()))) / ".config"
    )
    return base / "systemd" / "user" / UNIT_NAME


def render_unit(executable: str) -> str:
    return f"""\
[Unit]
Description=Voice Input dictation daemon
Documentation=https://github.com/kursluzz/voice-input
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart={executable} daemon
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
"""


class UserService:
    def __init__(self, path: Path | None = None, runner: Runner = run) -> None:
        self.path = path or unit_path()
        self._run = runner

    def _systemctl(self, *args: str, check: bool = True) -> str:
        result = self._run(["systemctl", "--user", *args], timeout=20.0)
        if check and result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise CommandFailedError(f"systemctl --user {' '.join(args)} failed: {detail}")
        return result.stdout.strip()

    def install(self, executable: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(render_unit(executable), encoding="utf-8")
        self._systemctl("daemon-reload")
        self._systemctl("enable", "--now", UNIT_NAME)

    def remove(self) -> bool:
        if not self.path.exists():
            return False
        self._systemctl("disable", "--now", UNIT_NAME, check=False)
        self.path.unlink()
        self._systemctl("daemon-reload")
        return True

    def is_active(self) -> bool:
        return self._systemctl("is-active", UNIT_NAME, check=False) == "active"
