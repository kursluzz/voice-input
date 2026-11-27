from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from voice_input import cli
from voice_input.config import ClipboardBackend, Config, InsertMethod
from voice_input.doctor import (
    Check,
    Level,
    check_clipboard,
    check_insertion,
    check_models,
    check_session,
)
from voice_input.system import Session


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    for name in ("VOICE_INPUT_CONFIG", "VOICE_INPUT_MODEL", "VOICE_INPUT_LANGUAGE"):
        monkeypatch.delenv(name, raising=False)


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("voice-input ")


def test_config_example_is_valid_toml(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["config", "--example"]) == 0
    tomllib.loads(capsys.readouterr().out)


def test_config_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["config", "--path"]) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / "config/voice-input/config.toml")


def test_config_shows_effective_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "c.toml"
    path.write_text('language = "he"\n[models]\nhe = "turbo"\n')
    assert cli.main(["--config", str(path), "config"]) == 0
    out = capsys.readouterr().out
    assert "language = he" in out
    assert "models = {'he': 'turbo'}" in out


def test_invalid_config_exits_with_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "c.toml"
    path.write_text("beam_size = 0\n")
    assert cli.main(["--config", str(path), "config"]) == cli.EXIT_USAGE
    assert "beam_size" in capsys.readouterr().err


def test_transcribe_reports_unreadable_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bogus = tmp_path / "not-audio.wav"
    bogus.write_text("hello")
    monkeypatch.setattr(cli, "_transcriber", lambda config, model: None)
    assert cli.main(["transcribe", str(bogus)]) == cli.EXIT_FAILED
    assert "only WAV files are supported" in capsys.readouterr().err


def test_setup_uinput_dry_run_prints_the_commands(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("voice_input.insert.uinput.uinput_writable", lambda path=None: False)
    assert cli.main(["setup", "uinput", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "sudo tee /etc/udev/rules.d/70-voice-input-uinput.rules" in out
    assert "udevadm trigger" in out


def test_setup_service_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["setup", "service", "--dry-run"]) == 0
    assert "ExecStart=" in capsys.readouterr().out


def test_executable_prefers_the_installed_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/home/u/.local/bin/voice-input")
    assert cli.executable() == "/home/u/.local/bin/voice-input"
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert cli.executable().endswith(" -m voice_input")


def test_language_choices() -> None:
    assert cli.LANGUAGE_CHOICES == ("auto", "en", "ru", "he")


# --- doctor --------------------------------------------------------------------------------


def none(program: str) -> str | None:
    return None


def every(program: str) -> str | None:
    return f"/usr/bin/{program}"


def test_doctor_session_checks() -> None:
    assert check_session(Session("unknown", "")).level is Level.FAIL
    assert check_session(Session("wayland", "GNOME")).level is Level.OK


def test_doctor_clipboard() -> None:
    gnome, sway = Session("wayland", "GNOME"), Session("wayland", "SWAY")
    ok = check_clipboard(Config(), gnome, none, lambda: True)
    assert (ok.level, ok.detail) == (Level.OK, "X11 selections (through XWayland)")
    missing = check_clipboard(Config(), sway, none, lambda: False)
    assert missing.level is Level.FAIL
    assert "wl-clipboard" in missing.hint
    assert check_clipboard(Config(), sway, every, lambda: False).level is Level.OK
    forced = Config(clipboard=ClipboardBackend.WL_CLIPBOARD)
    assert check_clipboard(forced, gnome, every, lambda: True).level is Level.WARN
    no_x = check_clipboard(Config(), Session("x11", "XFCE"), every, lambda: False)
    assert no_x.level is Level.FAIL


def test_doctor_insertion() -> None:
    gnome = Session("wayland", "GNOME")
    clipboard_only = check_insertion(Config(), gnome, none, lambda: False)
    assert clipboard_only.level is Level.WARN
    assert "setup uinput" in clipboard_only.hint
    assert check_insertion(Config(), gnome, none, lambda: True).level is Level.OK
    forced = Config(insert_method=InsertMethod.UINPUT)
    assert check_insertion(forced, gnome, none, lambda: False).level is Level.FAIL
    ydotool = Config(insert_method=InsertMethod.YDOTOOL)
    assert check_insertion(ydotool, gnome, none, lambda: False).level is Level.FAIL
    wtype = Config(insert_method=InsertMethod.WTYPE)
    assert check_insertion(wtype, gnome, every, lambda: False).level is Level.WARN


def test_doctor_models() -> None:
    from voice_input.languages import Language

    config = Config(model="small", models={Language.HE: "turbo", Language.RU: "small"})
    checks = check_models(config, lambda name, root: name == "small")
    assert [(c.name, c.level) for c in checks] == [
        ("model small", Level.OK),
        ("model turbo", Level.WARN),
    ]


def test_check_render() -> None:
    assert Check("x", Level.OK, "fine").render() == "✓ x: fine"
    assert Check("x", Level.WARN, "hmm", "do this").render() == "! x: hmm\n    → do this"


def test_setup_refuses_a_temporary_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "shutil.which", lambda name: "/home/u/.cache/uv/archive-v0/abc/bin/voice-input"
    )
    assert cli.main(["setup", "service", "--dry-run"]) == cli.EXIT_USAGE
    assert "uv tool install" in capsys.readouterr().err
