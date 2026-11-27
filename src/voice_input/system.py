"""Running external commands and describing the desktop session."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

DEFAULT_TIMEOUT: Final = 5.0


class CommandNotFoundError(RuntimeError):
    def __init__(self, program: str, hint: str = "") -> None:
        message = f"{program} is not installed"
        super().__init__(f"{message}. {hint}" if hint else message)
        self.program = program


class CommandFailedError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Runner(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        capture: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> CommandResult: ...


def run(
    args: Sequence[str],
    *,
    input_text: str | None = None,
    capture: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> CommandResult:
    """Run a command and return its result. Raises :class:`CommandNotFoundError`.

    Use ``capture=False`` for programs that fork a background child holding stdout open,
    such as ``wl-copy`` and ``xclip``: capturing would wait for that child to exit.
    """
    output = subprocess.PIPE if capture else subprocess.DEVNULL
    try:
        completed = subprocess.run(
            list(args),
            input=input_text.encode("utf-8") if input_text is not None else None,
            stdin=None if input_text is not None else subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise CommandNotFoundError(args[0]) from None
    except subprocess.TimeoutExpired:
        raise CommandFailedError(f"{args[0]} did not finish within {timeout:g} s") from None
    decode: Callable[[bytes | None], str] = lambda b: (b or b"").decode("utf-8", "replace")  # noqa: E731
    return CommandResult(completed.returncode, decode(completed.stdout), decode(completed.stderr))


Which = Callable[[str], str | None]


@dataclass(frozen=True)
class Session:
    """The graphical session the daemon runs in."""

    kind: str  # "wayland", "x11" or "unknown"
    desktop: str  # XDG_CURRENT_DESKTOP, upper case, for example "UBUNTU:GNOME"

    @property
    def is_gnome(self) -> bool:
        return "GNOME" in self.desktop

    @property
    def is_kde(self) -> bool:
        return "KDE" in self.desktop


def detect_session(environ: Mapping[str, str] | None = None) -> Session:
    env = os.environ if environ is None else environ
    kind = env.get("XDG_SESSION_TYPE", "").strip().lower()
    if kind not in {"wayland", "x11"}:
        if env.get("WAYLAND_DISPLAY"):
            kind = "wayland"
        elif env.get("DISPLAY"):
            kind = "x11"
        else:
            kind = "unknown"
    return Session(kind=kind, desktop=env.get("XDG_CURRENT_DESKTOP", "").upper())


def which(program: str) -> str | None:
    return shutil.which(program)
