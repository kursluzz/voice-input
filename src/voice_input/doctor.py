"""``voice-input doctor``: check everything dictation depends on and say how to fix problems."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from voice_input import paths
from voice_input.config import ClipboardBackend, Config, InsertMethod
from voice_input.insert.inserter import choose_method
from voice_input.insert.uinput import UINPUT_PATH, uinput_writable
from voice_input.insert.xselection import x11_available
from voice_input.ipc.client import DaemonNotRunningError, send
from voice_input.ipc.protocol import Command, Request
from voice_input.system import Session, Which, which


class Level(StrEnum):
    OK = "ok"
    INFO = "info"
    WARN = "warn"
    FAIL = "fail"


SYMBOLS = {Level.OK: "✓", Level.INFO: "•", Level.WARN: "!", Level.FAIL: "✗"}


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    detail: str
    hint: str = ""

    def render(self) -> str:
        line = f"{SYMBOLS[self.level]} {self.name}: {self.detail}"
        return f"{line}\n    → {self.hint}" if self.hint else line


def check_session(session: Session) -> Check:
    if session.kind == "unknown":
        return Check(
            "session",
            Level.FAIL,
            "no graphical session found (neither WAYLAND_DISPLAY nor DISPLAY is set)",
            "run Voice Input inside your desktop session",
        )
    desktop = session.desktop or "unknown desktop"
    return Check("session", Level.OK, f"{session.kind} on {desktop}")


def check_clipboard(
    config: Config, session: Session, find: Which, x11_ok: Callable[[], bool]
) -> Check:
    from voice_input.insert.clipboard import choose_backend

    backend = choose_backend(config.clipboard, session, x11_ok=x11_ok)
    if backend is ClipboardBackend.X11:
        if x11_ok():
            where = "through XWayland" if session.kind == "wayland" else "X11"
            return Check("clipboard", Level.OK, f"X11 selections ({where})")
        return Check(
            "clipboard",
            Level.FAIL,
            "cannot connect to the X server (DISPLAY)",
            'set clipboard = "wl-clipboard" in the configuration, or enable XWayland',
        )
    if not find("wl-copy"):
        return Check("clipboard", Level.FAIL, "wl-copy is missing", "sudo apt install wl-clipboard")
    if session.is_gnome:
        return Check(
            "clipboard",
            Level.WARN,
            "wl-clipboard on GNOME hangs in the background",
            'use clipboard = "auto" (X11 selections through XWayland)',
        )
    return Check("clipboard", Level.OK, "wl-clipboard")


def check_insertion(
    config: Config, session: Session, find: Which, uinput_ok: Callable[[], bool]
) -> Check:
    method = choose_method(config.insert_method, session, which=find, uinput_ok=uinput_ok)
    chosen = f"{method.value}" + (" (auto)" if config.insert_method is InsertMethod.AUTO else "")
    if method is InsertMethod.CLIPBOARD:
        hint = "run `voice-input setup uinput` so the text is pasted automatically"
        return Check(
            "typing", Level.WARN, f"{chosen}: text is only copied, paste it yourself", hint
        )
    if method is InsertMethod.UINPUT and not uinput_ok():
        return Check(
            "typing",
            Level.FAIL,
            f"{chosen}: no write access to {UINPUT_PATH}",
            "run `voice-input setup uinput`",
        )
    for tool in ("ydotool", "wtype", "xdotool"):
        if method.value == tool and not find(tool):
            return Check("typing", Level.FAIL, f"{chosen}: {tool} is missing", f"install {tool}")
    detail = f"{chosen}, paste keys {config.paste_keys}"
    if method is InsertMethod.WTYPE and (session.is_gnome or session.is_kde):
        return Check("typing", Level.WARN, detail, "wtype does not work on GNOME or KDE")
    return Check("typing", Level.OK, detail)


def check_microphone() -> Check:
    try:
        from voice_input.audio.recorder import input_devices

        devices = input_devices()
    except Exception as exc:
        return Check("microphone", Level.FAIL, str(exc), "sudo apt install libportaudio2")
    if not devices:
        return Check("microphone", Level.FAIL, "no input device found", "connect a microphone")
    default = next((name for _, name, is_default in devices if is_default), devices[0][1])
    return Check("microphone", Level.OK, f"{len(devices)} input device(s); default: {default}")


def check_models(config: Config, cached: Callable[[str, Path | None], bool]) -> list[Check]:
    names = dict.fromkeys([config.model, *config.models.values()])
    checks: list[Check] = []
    for name in names:
        if cached(name, config.model_dir):
            checks.append(Check(f"model {name}", Level.OK, "downloaded"))
        else:
            checks.append(
                Check(
                    f"model {name}",
                    Level.WARN,
                    "not downloaded yet; the first dictation will download it",
                    f"voice-input download {name}",
                )
            )
    return checks


def check_notifications(find: Which) -> Check:
    if find("notify-send"):
        return Check("notifications", Level.OK, "notify-send found")
    return Check(
        "notifications", Level.WARN, "notify-send is missing", "sudo apt install libnotify-bin"
    )


def check_daemon(socket: Path) -> Check:
    try:
        reply = send(socket, Request(Command.STATUS), timeout=2.0)
    except DaemonNotRunningError:
        return Check(
            "daemon",
            Level.INFO,
            "not running (a shortcut starts it on demand)",
            "voice-input setup service   # to start it at login",
        )
    except Exception as exc:
        return Check("daemon", Level.WARN, f"not answering: {exc}")
    detail = (
        f"running (pid {reply.get('pid')}, {reply.get('state')}, "
        f"model {reply.get('model')} {reply.get('model_state')}, "
        f"typing via {reply.get('insert_method')})"
    )
    return Check("daemon", Level.OK, detail)


def check_shortcuts(session: Session) -> Check:
    if not session.is_gnome:
        return Check(
            "shortcuts",
            Level.INFO,
            f"automatic setup supports GNOME only (desktop: {session.desktop or 'unknown'})",
            "bind `voice-input toggle --lang en|ru|he` to keys in your desktop's settings",
        )
    from voice_input.desktop.gnome import GnomeShortcuts

    shortcuts = GnomeShortcuts()
    try:
        installed = shortcuts.installed()
    except Exception as exc:
        return Check("shortcuts", Level.WARN, f"cannot read GNOME settings: {exc}")
    if not installed:
        return Check("shortcuts", Level.WARN, "none installed", "voice-input setup shortcuts")
    bindings = ", ".join(binding for binding, _ in installed.values())
    return Check("shortcuts", Level.OK, f"{len(installed)} installed: {bindings}")


def run_checks(config: Config, session: Session, *, find: Which = which) -> list[Check]:
    from voice_input.stt.whisper import cuda_available, is_model_cached

    checks = [
        check_session(session),
        check_clipboard(config, session, find, x11_available),
        check_insertion(config, session, find, uinput_writable),
        check_microphone(),
        *check_models(config, is_model_cached),
        Check(
            "compute",
            Level.INFO,
            "CUDA GPU available" if cuda_available() else "CPU (no CUDA GPU found)",
        ),
        check_notifications(find),
        check_daemon(paths.socket_path()),
        check_shortcuts(session),
    ]
    return checks
