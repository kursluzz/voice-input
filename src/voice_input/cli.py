"""Command line interface: ``voice-input <command>``.

Exit status: 0 success, 1 the command failed, 2 bad usage or configuration, 3 the daemon could
not be reached.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import shutil
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from voice_input import __version__, paths
from voice_input.config import EXAMPLE_CONFIG, Config, ConfigError, load_config
from voice_input.ipc.protocol import Command, Request
from voice_input.languages import AUTO, SUPPORTED, Language, parse_language
from voice_input.logging_setup import configure_logging

EXIT_OK: Final = 0
EXIT_FAILED: Final = 1
EXIT_USAGE: Final = 2
EXIT_NO_DAEMON: Final = 3

_log = logging.getLogger("voice_input.cli")
LANGUAGE_CHOICES: Final = (AUTO, *(lang.value for lang in SUPPORTED))


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_FAILED) -> None:
        super().__init__(message)
        self.code = code


def executable() -> str:
    """How shortcuts and the service should run Voice Input."""
    found = shutil.which("voice-input")
    return found if found else f"{sys.executable} -m voice_input"


_TEMPORARY_MARKERS: Final = ("/.cache/uv/", "/archive-v0/", "/pipx/.cache/", "/tmp/")


def stable_executable() -> str:
    """:func:`executable`, refusing locations that disappear (``uvx``, ``pipx run``)."""
    command = executable()
    if any(marker in command for marker in _TEMPORARY_MARKERS):
        raise CliError(
            f"voice-input runs from a temporary environment ({command}), so shortcuts and the "
            "service would break when it is cleaned up. Install it first: "
            "uv tool install git+https://github.com/kursluzz/voice-input",
            EXIT_USAGE,
        )
    return command


def _language(value: str | None) -> tuple[Language | None, bool]:
    """``(language, use_default)`` from a ``--lang`` option."""
    if value is None:
        return None, True
    return parse_language(value), False


def _interactive() -> bool:
    return sys.stdin.isatty() or sys.stderr.isatty()


def _notify_failure(message: str) -> None:
    """A shortcut has no terminal: show failures as a notification instead."""
    if _interactive():
        return
    from voice_input.desktop.notify import Notification, Notifier

    Notifier().send_now(Notification("Voice Input", message, transient=False))


# --- commands that talk to the daemon ------------------------------------------------------


def cmd_control(args: argparse.Namespace, config: Config) -> int:
    from voice_input.ipc.client import (
        DaemonNotRunningError,
        DaemonStartError,
        ensure_daemon,
        send,
    )

    command = Command(args.command)
    language, use_default = _language(getattr(args, "lang", None))
    socket = paths.socket_path()
    try:
        if command in (Command.TOGGLE, Command.START) and not args.no_autostart:
            ensure_daemon(socket)
        reply = send(socket, Request(command, language, use_default))
    except DaemonNotRunningError:
        if command is Command.SHUTDOWN:
            print("the daemon is not running")
            return EXIT_OK
        message = "the voice-input daemon is not running; start it with `voice-input daemon`"
        print(message, file=sys.stderr)
        return EXIT_NO_DAEMON
    except DaemonStartError as exc:
        _notify_failure(str(exc))
        print(exc, file=sys.stderr)
        return EXIT_NO_DAEMON
    if command is Command.STATUS:
        return _print_status(reply, as_json=args.json)
    message = str(reply.get("message", ""))
    if not reply.get("ok"):
        _notify_failure(message)
        print(message, file=sys.stderr)
        return EXIT_FAILED
    if not args.quiet:
        print(message)
    return EXIT_OK


def _print_status(reply: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(reply, ensure_ascii=False, indent=2))
    else:
        for key, value in reply.items():
            if key not in {"ok", "message"}:
                print(f"{key}: {value}")
    return EXIT_OK if reply.get("ok") else EXIT_FAILED


def cmd_daemon(args: argparse.Namespace, config: Config) -> int:
    from voice_input.daemon import run_daemon
    from voice_input.ipc.server import AlreadyRunningError

    configure_logging(config.log_level, paths.log_dir())
    try:
        run_daemon(config)
    except AlreadyRunningError as exc:
        print(exc, file=sys.stderr)
        return EXIT_FAILED
    return EXIT_OK


# --- commands that work without the daemon -------------------------------------------------


def _transcriber(config: Config, model: str | None) -> Any:
    from voice_input.stt.whisper import ModelSettings, WhisperTranscriber

    return WhisperTranscriber(
        model=model or config.model,
        models={} if model else dict(config.models),
        settings=ModelSettings(
            device=config.device,
            compute_type=config.compute_type,
            cpu_threads=config.cpu_threads,
            model_dir=config.model_dir,
        ),
        beam_size=config.beam_size,
        vad_filter=config.vad_filter,
    )


def _language_for_offline(args: argparse.Namespace, config: Config) -> Language | None:
    language, use_default = _language(args.lang)
    return config.language if use_default else language


def cmd_transcribe(args: argparse.Namespace, config: Config) -> int:
    from voice_input.audio.signal import read_wav
    from voice_input.postprocess import clean_segments

    transcriber = _transcriber(config, args.model)
    language = _language_for_offline(args, config)
    status = EXIT_OK
    for file in args.files:
        try:
            audio = read_wav(Path(file))
        except (OSError, ValueError, EOFError) as exc:
            print(f"{file}: cannot read: {exc} (only WAV files are supported)", file=sys.stderr)
            status = EXIT_FAILED
            continue
        transcript = transcriber.transcribe(audio, language)
        text = clean_segments(transcript.segments)
        if args.json:
            detected = transcript.language.value if transcript.language else None
            print(
                json.dumps(
                    {
                        "file": file,
                        "language": detected,
                        "text": text,
                        "audio_seconds": round(transcript.audio_seconds, 2),
                        "elapsed_seconds": round(transcript.elapsed_seconds, 2),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            prefix = f"{file}: " if len(args.files) > 1 else ""
            print(prefix + text)
    return status


def cmd_listen(args: argparse.Namespace, config: Config) -> int:
    from voice_input.audio.recorder import SoundDeviceRecorder
    from voice_input.postprocess import clean_segments

    language = _language_for_offline(args, config)
    transcriber = _transcriber(config, args.model)
    loader = threading.Thread(target=transcriber.preload, args=(language,), daemon=True)
    loader.start()
    limit = threading.Event()
    max_seconds = args.seconds or config.max_recording_seconds
    recorder = SoundDeviceRecorder(device=config.input_device, max_seconds=max_seconds)
    recording = recorder.start(limit.set)
    if args.seconds:
        print(f"Listening for {args.seconds:g} s…", file=sys.stderr)
        limit.wait(args.seconds + 1)
    else:
        print("Listening… press Enter to stop.", file=sys.stderr)

        def wait_for_enter() -> None:
            sys.stdin.readline()
            limit.set()

        threading.Thread(target=wait_for_enter, daemon=True).start()
        limit.wait()
    audio = recording.stop()
    print("Recognising…", file=sys.stderr)
    transcript = transcriber.transcribe(audio, language)
    print(clean_segments(transcript.segments))
    return EXIT_OK


def cmd_devices(args: argparse.Namespace, config: Config) -> int:
    from voice_input.audio.recorder import input_devices

    for index, name, is_default in input_devices():
        print(f"{index:3d}  {name}{'  (default)' if is_default else ''}")
    return EXIT_OK


def cmd_download(args: argparse.Namespace, config: Config) -> int:
    from voice_input.stt.whisper import download

    names = args.models or list(dict.fromkeys([config.model, *config.models.values()]))
    for name in names:
        print(f"downloading {name}…", file=sys.stderr)
        location = download(name, config.model_dir)
        print(f"{name}: {location}")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace, config: Config) -> int:
    from voice_input.doctor import Level, run_checks
    from voice_input.system import detect_session

    print(f"voice-input {__version__}  (config: {args.config or paths.config_file()})")
    checks = run_checks(config, detect_session())
    for check in checks:
        print(check.render())
    return EXIT_FAILED if any(c.level is Level.FAIL for c in checks) else EXIT_OK


def cmd_config(args: argparse.Namespace, config: Config) -> int:
    if args.path:
        print(args.config or paths.config_file())
        return EXIT_OK
    if args.example:
        print(EXAMPLE_CONFIG, end="")
        return EXIT_OK
    for field in dataclasses.fields(config):
        value = getattr(config, field.name)
        if field.name == "language":
            value = value.value if value else AUTO
        elif isinstance(value, dict):
            value = {str(k): v for k, v in value.items()}
        print(f"{field.name} = {value}")
    return EXIT_OK


# --- setup ---------------------------------------------------------------------------------


def _run_steps(steps: Sequence[Any], dry_run: bool) -> None:
    import subprocess

    from voice_input.desktop.udev import shell_script

    print(shell_script(list(steps)))
    if dry_run:
        return
    for step in steps:
        completed = subprocess.run(
            list(step.args),
            input=step.input_text.encode() if step.input_text is not None else None,
            stdout=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode != 0:
            raise CliError(f"command failed: {step.shell()}")


def setup_uinput(args: argparse.Namespace) -> None:
    from voice_input.desktop import udev
    from voice_input.insert.uinput import uinput_writable

    if args.remove:
        print("Removing the uinput rule (needs sudo):")
        _run_steps(udev.remove_steps(), args.dry_run)
        return
    if uinput_writable() and not args.force:
        print("uinput: already writable by you; nothing to do (use --force to reinstall).")
        return
    print("Letting your user create a virtual keyboard (needs sudo):")
    _run_steps(udev.install_steps(), args.dry_run)
    if not args.dry_run:
        if uinput_writable():
            print("uinput: ready.")
        else:
            print(
                "uinput: the rule is installed but access is not granted yet. "
                "Log out and back in, or reboot."
            )


def setup_shortcuts(args: argparse.Namespace, config: Config) -> None:
    from voice_input.desktop.gnome import GnomeShortcuts, plan

    shortcuts = GnomeShortcuts()
    if not shortcuts.available():
        raise CliError(
            "GNOME settings are not available. Bind `voice-input toggle --lang en|ru|he` "
            "to keys in your desktop's keyboard settings instead."
        )
    if args.remove:
        removed = shortcuts.remove() if not args.dry_run else list(shortcuts.installed())
        print(f"shortcuts: removed {len(removed)}")
        return
    planned = plan(config.shortcuts, stable_executable())
    for item in planned:
        conflicts = shortcuts.conflicts(item.binding)
        warning = f"   ! also used by: {', '.join(conflicts)}" if conflicts else ""
        print(f"  {item.binding:<20} {item.command}{warning}")
    if not args.dry_run:
        shortcuts.install(planned)
        print(f"shortcuts: {len(planned)} installed")


def setup_service(args: argparse.Namespace) -> None:
    from voice_input.desktop.systemd import UserService, render_unit
    from voice_input.ipc.client import DaemonNotRunningError, send

    service = UserService()
    if args.remove:
        if args.dry_run:
            print(f"would remove {service.path}")
            return
        removed = service.remove()
        print(f"service: {'removed' if removed else 'not installed'}")
        return
    command = stable_executable()
    print(f"{service.path}:\n{render_unit(command)}")
    if args.dry_run:
        return
    try:  # a daemon started on demand would block the service's own daemon
        send(paths.socket_path(), Request(Command.SHUTDOWN), timeout=2.0)
    except (DaemonNotRunningError, OSError):
        pass
    else:
        import time

        time.sleep(1.0)
    service.install(command)
    print("service: enabled and started")


def cmd_setup(args: argparse.Namespace, config: Config) -> int:
    targets = ["uinput", "shortcuts", "service"] if args.target == "all" else [args.target]
    for target in targets:
        if target == "uinput":
            setup_uinput(args)
        elif target == "shortcuts":
            setup_shortcuts(args, config)
        else:
            setup_service(args)
    return EXIT_OK


# --- parser --------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-input",
        description="Offline voice typing: speak, and the text appears in the focused window.",
    )
    parser.add_argument("--version", action="version", version=f"voice-input {__version__}")
    parser.add_argument("--config", type=Path, help="configuration file to use")
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), help="override log level"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def control(name: str, text: str, *, language: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=text, description=text)
        if language:
            p.add_argument(
                "--lang",
                "-l",
                choices=LANGUAGE_CHOICES,
                help="language to dictate in (default: the configured language)",
            )
            p.add_argument(
                "--no-autostart",
                action="store_true",
                help="fail instead of starting the daemon when it is not running",
            )
        p.add_argument("--quiet", "-q", action="store_true", help="print nothing on success")
        p.set_defaults(handler=cmd_control, no_autostart=True, json=False)
        if language:
            p.set_defaults(no_autostart=False)
        return p

    control(
        "toggle", "start dictating, or stop and type the text (bind this to a key)", language=True
    )
    control("start", "start dictating", language=True)
    control("stop", "stop dictating and type the text")
    control("cancel", "stop dictating and throw the recording away")
    status = control("status", "show what the daemon is doing")
    status.add_argument("--json", action="store_true", help="print JSON")
    control("shutdown", "stop the daemon")

    p = sub.add_parser("daemon", help="run the background daemon in the foreground")
    p.set_defaults(handler=cmd_daemon)

    p = sub.add_parser("transcribe", help="transcribe WAV files and print the text")
    p.add_argument("files", nargs="+", metavar="FILE")
    p.add_argument("--lang", "-l", choices=LANGUAGE_CHOICES)
    p.add_argument("--model", "-m", help="Whisper model (default: from the configuration)")
    p.add_argument("--json", action="store_true", help="one JSON object per file")
    p.set_defaults(handler=cmd_transcribe)

    p = sub.add_parser("listen", help="record from the microphone and print the text")
    p.add_argument("--lang", "-l", choices=LANGUAGE_CHOICES)
    p.add_argument("--model", "-m")
    p.add_argument("--seconds", "-s", type=float, help="record this long instead of until Enter")
    p.set_defaults(handler=cmd_listen)

    p = sub.add_parser("devices", help="list microphones")
    p.set_defaults(handler=cmd_devices)

    p = sub.add_parser("download", help="download Whisper models ahead of time")
    p.add_argument("models", nargs="*", metavar="MODEL", help="default: the configured models")
    p.set_defaults(handler=cmd_download)

    p = sub.add_parser("doctor", help="check the installation and explain how to fix problems")
    p.set_defaults(handler=cmd_doctor)

    p = sub.add_parser("config", help="show the effective configuration")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--example", action="store_true", help="print a commented example file")
    group.add_argument("--path", action="store_true", help="print the configuration file path")
    p.set_defaults(handler=cmd_config)

    p = sub.add_parser(
        "setup",
        help="install shortcuts, the login service or the uinput permission",
        description=(
            "shortcuts: GNOME keyboard shortcuts. service: start the daemon at login "
            "(systemd user service). uinput: let your user create the virtual keyboard that "
            "pastes the text (asks for your sudo password). all: everything."
        ),
    )
    p.add_argument("target", choices=("shortcuts", "service", "uinput", "all"))
    p.add_argument("--remove", action="store_true", help="undo the setup")
    p.add_argument("--dry-run", action="store_true", help="show what would be done")
    p.add_argument("--force", action="store_true", help="reinstall even if already set up")
    p.set_defaults(handler=cmd_setup)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.log_level:
        config = dataclasses.replace(config, log_level=args.log_level)
    if args.command != "daemon":
        configure_logging(config.log_level, console_level="WARNING")
    try:
        code: int = args.handler(args, config)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _log.debug("command failed", exc_info=True)
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED
    return code
