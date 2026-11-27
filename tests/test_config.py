from __future__ import annotations

import tomllib
from dataclasses import fields
from pathlib import Path

import pytest

from voice_input.config import (
    DEFAULT_SHORTCUTS,
    EXAMPLE_CONFIG,
    Config,
    ConfigError,
    InsertMethod,
    Shortcut,
    load_config,
    parse_settings,
)
from voice_input.languages import Language


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "absent.toml", environ={})
    assert config == Config()
    assert config.language is None
    assert config.model == "small"
    assert config.shortcuts[Shortcut.DEFAULT] == "<Super>t"


def test_file_values_are_parsed(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
language = "ru"
model = "base"
beam_size = 1
insert_method = "clipboard"
paste_keys = "Ctrl+Shift+V"
max_recording_seconds = 60
input_device = 3
[models]
he = "large-v3-turbo"
[shortcuts]
ru = "<Super>r"
cancel = "<Super>Escape"
""",
    )
    config = load_config(path, environ={})
    assert config.language is Language.RU
    assert config.model == "base"
    assert config.beam_size == 1
    assert config.insert_method is InsertMethod.CLIPBOARD
    assert config.paste_keys == "ctrl+shift+v"
    assert config.max_recording_seconds == 60.0
    assert config.input_device == "3"
    assert config.models == {Language.HE: "large-v3-turbo"}
    assert config.shortcuts[Shortcut.RU] == "<Super>r"
    assert config.shortcuts[Shortcut.EN] == DEFAULT_SHORTCUTS[Shortcut.EN]
    assert config.shortcuts[Shortcut.CANCEL] == "<Super>Escape"


def test_model_for_uses_per_language_override() -> None:
    config = Config(model="small", models={Language.HE: "turbo"})
    assert config.model_for(Language.HE) == "turbo"
    assert config.model_for(Language.RU) == "small"
    assert config.model_for(None) == "small"


def test_environment_overrides_file(tmp_path: Path) -> None:
    path = write(tmp_path, 'model = "base"\nsound_cues = true\n')
    env = {"VOICE_INPUT_MODEL": "medium", "VOICE_INPUT_SOUND_CUES": "off"}
    config = load_config(path, environ=env)
    assert config.model == "medium"
    assert config.sound_cues is False


def test_config_path_from_environment(tmp_path: Path) -> None:
    path = write(tmp_path, 'language = "he"\n')
    config = load_config(environ={"VOICE_INPUT_CONFIG": str(path)})
    assert config.language is Language.HE


def test_default_path_uses_xdg(tmp_path: Path) -> None:
    (tmp_path / "voice-input").mkdir()
    (tmp_path / "voice-input" / "config.toml").write_text('language = "en"\n')
    config = load_config(environ={"XDG_CONFIG_HOME": str(tmp_path)})
    assert config.language is Language.EN


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("colour = 1", "unknown setting 'colour'"),
        ('language = "de"', "unsupported language"),
        ("beam_size = 0", "between 1 and 20"),
        ("beam_size = true", "whole number"),
        ('device = "tpu"', "one of auto, cpu, cuda"),
        ('insert_method = "magic"', "insert_method"),
        ('paste_keys = "ctrl+nosuchkey"', "unknown key"),
        ("cue_volume = 2", "between 0 and 1"),
        ('model = ""', "must not be empty"),
        ('[models]\nauto = "x"', "top-level 'model'"),
        ('[shortcuts]\nfr = "<Super>f"', "unknown action"),
        ("sound_cues = 3", "true or false"),
        ("not toml [", "invalid TOML"),
    ],
)
def test_invalid_values_are_rejected(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text), environ={})


def test_invalid_environment_value_names_the_source() -> None:
    with pytest.raises(ConfigError, match="environment: beam_size"):
        load_config(Path("/nonexistent"), environ={"VOICE_INPUT_BEAM_SIZE": "lots"})


def test_example_config_is_valid_and_matches_defaults() -> None:
    parsed = parse_settings(tomllib.loads(EXAMPLE_CONFIG), source="example")
    assert Config(**parsed) == Config()


def test_example_config_mentions_every_setting() -> None:
    for field in fields(Config):
        assert field.name in EXAMPLE_CONFIG, field.name
