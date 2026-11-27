"""Permission to use ``/dev/uinput`` for the logged-in user.

The rule tags the device ``uaccess``: systemd-logind then grants the user at the active seat
access through an ACL. Unlike adding the user to the ``input`` group, this does not let the
user read other keyboards, and it needs no new login. The file name sorts before
``73-seat-late.rules``, which applies the tag.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Final

RULE_PATH: Final = Path("/etc/udev/rules.d/70-voice-input-uinput.rules")
MODULES_PATH: Final = Path("/etc/modules-load.d/voice-input-uinput.conf")

RULE: Final = (
    "# Installed by voice-input: lets the logged-in user create a virtual keyboard.\n"
    'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"\n'
)
MODULES: Final = "# Installed by voice-input: load uinput at boot.\nuinput\n"


@dataclass(frozen=True)
class Step:
    """One privileged command, optionally fed ``input_text`` on stdin."""

    args: tuple[str, ...]
    input_text: str | None = None

    def shell(self) -> str:
        command = shlex.join(self.args)
        if self.input_text is None:
            return command
        return f"printf '%s' {shlex.quote(self.input_text)} | {command} > /dev/null"


_RELOAD: Final = (
    Step(("sudo", "udevadm", "control", "--reload-rules")),
    Step(("sudo", "udevadm", "trigger", "--name-match=uinput")),
)


def install_steps() -> list[Step]:
    """Install the rule, load the module, and apply the rule to the existing device."""
    return [
        Step(("sudo", "tee", str(RULE_PATH)), RULE),
        Step(("sudo", "tee", str(MODULES_PATH)), MODULES),
        Step(("sudo", "modprobe", "uinput")),
        *_RELOAD,
    ]


def remove_steps() -> list[Step]:
    return [Step(("sudo", "rm", "-f", str(RULE_PATH), str(MODULES_PATH))), *_RELOAD]


def shell_script(steps: list[Step]) -> str:
    return "\n".join(step.shell() for step in steps)
