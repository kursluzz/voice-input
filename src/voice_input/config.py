"""Configuration: built-in defaults, a TOML file and ``VOICE_INPUT_*`` environment variables.

Precedence, lowest first: defaults, the configuration file, environment variables, and finally
command-line options (applied by the CLI with :func:`dataclasses.replace`). Unknown keys and
invalid values raise :class:`ConfigError` with a message that names the offending key.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from voice_input import paths
from voice_input.languages import Language, parse_language


class ConfigError(ValueError):
    """The configuration file or an environment variable holds an invalid value."""


class InsertMethod(StrEnum):
    """How the transcript reaches the focused window."""

    AUTO = "auto"  # pick the best available backend for this session
    UINPUT = "uinput"  # kernel virtual keyboard, works on every Wayland compositor and X11
    YDOTOOL = "ydotool"  # the ydotool daemon (also uinput, but run by ydotoold)
    WTYPE = "wtype"  # virtual-keyboard protocol: wlroots compositors (Sway, Hyprland), not GNOME
    XDOTOOL = "xdotool"  # X11 sessions
    CLIPBOARD = "clipboard"  # copy only; the user pastes by hand


class ClipboardBackend(StrEnum):
    """Which mechanism owns the clipboard."""

    AUTO = "auto"  # X11 selections on X11 and on GNOME (through XWayland), else wl-clipboard
    X11 = "x11"
    WL_CLIPBOARD = "wl-clipboard"


class Shortcut(StrEnum):
    """Actions that get a desktop keyboard shortcut."""

    DEFAULT = "default"  # toggle in the configured default language
    EN = "en"
    RU = "ru"
    HE = "he"
    CANCEL = "cancel"


DEFAULT_SHORTCUTS: Final[Mapping[Shortcut, str]] = {
    Shortcut.DEFAULT: "<Super>t",
    Shortcut.EN: "<Shift><Super>e",
    Shortcut.RU: "<Shift><Super>r",
    Shortcut.HE: "<Shift><Super>h",
    Shortcut.CANCEL: "",
}

LOG_LEVELS: Final = ("DEBUG", "INFO", "WARNING", "ERROR")
DEVICES: Final = ("auto", "cpu", "cuda")


@dataclass(frozen=True)
class Config:
    """Effective settings. Every field has a default, so an empty file is valid."""

    language: Language | None = None  # None means automatic detection
    model: str = "small"
    models: Mapping[Language, str] = field(default_factory=dict)
    device: str = "auto"
    compute_type: str = "auto"
    cpu_threads: int = 0
    beam_size: int = 5
    vad_filter: bool = True
    model_dir: Path | None = None
    preload_model: bool = True
    input_device: str | None = None
    max_recording_seconds: float = 300.0
    min_recording_seconds: float = 0.3
    sound_cues: bool = True
    cue_volume: float = 0.25
    notifications: bool = True
    insert_method: InsertMethod = InsertMethod.AUTO
    clipboard: ClipboardBackend = ClipboardBackend.AUTO
    paste_keys: str = "shift+insert"
    restore_clipboard: bool = False
    trailing_space: bool = True
    log_level: str = "INFO"
    shortcuts: Mapping[Shortcut, str] = field(default_factory=lambda: dict(DEFAULT_SHORTCUTS))

    def model_for(self, language: Language | None) -> str:
        """The Whisper model used for ``language`` (the default model for automatic detection)."""
        if language is not None and language in self.models:
            return self.models[language]
        return self.model


# --- value parsers -------------------------------------------------------------------------


def _expect(value: Any, kind: type | tuple[type, ...], key: str, what: str) -> Any:
    # bool is a subclass of int; never accept it where a number is expected.
    if isinstance(value, bool) and kind is not bool:
        raise ConfigError(f"{key}: expected {what}, got {value!r}")
    if not isinstance(value, kind):
        raise ConfigError(f"{key}: expected {what}, got {value!r}")
    return value


def _str(key: str, value: Any) -> str:
    text = _expect(value, str, key, "a string")
    if not text.strip():
        raise ConfigError(f"{key}: must not be empty")
    return str(text).strip()


def _bool(key: str, value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(_expect(value, bool, key, "true or false"))


def _number(key: str, value: Any, low: float, high: float) -> float:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            raise ConfigError(f"{key}: expected a number, got {value!r}") from None
    number = float(_expect(value, (int, float), key, "a number"))
    if not low <= number <= high:
        raise ConfigError(f"{key}: must be between {low:g} and {high:g}, got {number:g}")
    return number


def _int(key: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            raise ConfigError(f"{key}: expected a whole number, got {value!r}") from None
    number = int(_expect(value, int, key, "a whole number"))
    if not low <= number <= high:
        raise ConfigError(f"{key}: must be between {low} and {high}, got {number}")
    return number


def _choice(key: str, value: Any, choices: tuple[str, ...]) -> str:
    text = _str(key, value)
    normalized = text.lower() if key != "log_level" else text.upper()
    if normalized not in choices:
        raise ConfigError(f"{key}: must be one of {', '.join(choices)}, got {text!r}")
    return normalized


def _language(key: str, value: Any) -> Language | None:
    try:
        return parse_language(_str(key, value))
    except ValueError as exc:
        raise ConfigError(f"{key}: {exc}") from None


def _insert_method(key: str, value: Any) -> InsertMethod:
    return InsertMethod(_choice(key, value, tuple(InsertMethod)))


def _paste_keys(key: str, value: Any) -> str:
    # Imported here to keep config free of the insertion package at import time.
    from voice_input.insert.keys import parse_combo

    text = _str(key, value).lower()
    try:
        parse_combo(text)
    except ValueError as exc:
        raise ConfigError(f"{key}: {exc}") from None
    return text


def _models(key: str, value: Any) -> dict[Language, str]:
    table = _expect(value, dict, key, 'a table such as { he = "large-v3-turbo" }')
    result: dict[Language, str] = {}
    for name, model in table.items():
        language = _language(f"{key}.{name}", name)
        if language is None:
            raise ConfigError(f"{key}.{name}: use the top-level 'model' for automatic detection")
        result[language] = _str(f"{key}.{name}", model)
    return result


def _shortcuts(key: str, value: Any) -> dict[Shortcut, str]:
    table = _expect(value, dict, key, 'a table such as { ru = "<Shift><Super>r" }')
    result = dict(DEFAULT_SHORTCUTS)
    for name, binding in table.items():
        try:
            action = Shortcut(str(name).lower())
        except ValueError:
            choices = ", ".join(Shortcut)
            raise ConfigError(f"{key}.{name}: unknown action; choose from {choices}") from None
        # An empty string disables that shortcut.
        result[action] = str(_expect(binding, str, f"{key}.{name}", "a string")).strip()
    return result


def _optional_str(key: str, value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)  # an input device can be given by its index
    text = _expect(value, str, key, "a string").strip()
    return text or None


def _path(key: str, value: Any) -> Path | None:
    text = _expect(value, str, key, "a path").strip()
    return Path(text).expanduser() if text else None


_PARSERS: Final[dict[str, Callable[[str, Any], Any]]] = {
    "language": _language,
    "model": _str,
    "models": _models,
    "device": lambda k, v: _choice(k, v, DEVICES),
    "compute_type": _str,
    "cpu_threads": lambda k, v: _int(k, v, 0, 256),
    "beam_size": lambda k, v: _int(k, v, 1, 20),
    "vad_filter": _bool,
    "model_dir": _path,
    "preload_model": _bool,
    "input_device": _optional_str,
    "max_recording_seconds": lambda k, v: _number(k, v, 1.0, 3600.0),
    "min_recording_seconds": lambda k, v: _number(k, v, 0.0, 10.0),
    "sound_cues": _bool,
    "cue_volume": lambda k, v: _number(k, v, 0.0, 1.0),
    "notifications": _bool,
    "insert_method": _insert_method,
    "clipboard": lambda k, v: ClipboardBackend(_choice(k, v, tuple(ClipboardBackend))),
    "paste_keys": _paste_keys,
    "restore_clipboard": _bool,
    "trailing_space": _bool,
    "log_level": lambda k, v: _choice(k, v, LOG_LEVELS),
    "shortcuts": _shortcuts,
}

assert set(_PARSERS) == {f.name for f in fields(Config)}, "every Config field needs a parser"

ENV_PREFIX: Final = "VOICE_INPUT_"
# Settings that make sense as environment variables (tables do not).
_ENV_KEYS: Final = tuple(k for k in _PARSERS if k not in {"models", "shortcuts"})


def parse_settings(data: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    """Validate a mapping of raw settings and return parsed values keyed by field name."""
    parsed: dict[str, Any] = {}
    for key, value in data.items():
        parser = _PARSERS.get(key)
        if parser is None:
            known = ", ".join(sorted(_PARSERS))
            raise ConfigError(f"{source}: unknown setting {key!r}. Known settings: {known}")
        try:
            parsed[key] = parser(key, value)
        except ConfigError as exc:
            raise ConfigError(f"{source}: {exc}") from None
    return parsed


def read_config_file(path: Path) -> dict[str, Any]:
    """Read and validate a TOML file. A missing file yields no settings."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from None
    return parse_settings(data, source=str(path))


def read_environment(environ: Mapping[str, str]) -> dict[str, Any]:
    data = {
        key: environ[ENV_PREFIX + key.upper()]
        for key in _ENV_KEYS
        if ENV_PREFIX + key.upper() in environ
    }
    return parse_settings(data, source="environment")


def load_config(
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Build the effective configuration from the file and the environment."""
    env = os.environ if environ is None else environ
    if path is None:
        override = env.get(ENV_PREFIX + "CONFIG", "").strip()
        path = Path(override).expanduser() if override else paths.config_file(env)
    settings = read_config_file(path)
    settings.update(read_environment(env))
    return Config(**settings)


EXAMPLE_CONFIG: Final = """\
# Voice Input configuration. Every setting is optional; the values shown are the defaults.
# Location: ~/.config/voice-input/config.toml (or $XDG_CONFIG_HOME/voice-input/config.toml).

# Language of the default shortcut: auto, en, ru or he.
language = "auto"

# Whisper model: tiny, base, small, medium, large-v3, large-v3-turbo, distil-large-v3,
# or a Hugging Face repository with a CTranslate2 model.
model = "small"
# Optional per-language models, for example a better Hebrew model:
# [models]
# he = "ivrit-ai/whisper-large-v3-turbo-ct2"

device = "auto"          # auto, cpu or cuda
compute_type = "auto"    # auto (int8 on CPU, float16 on CUDA), int8, float16, float32 ...
cpu_threads = 0          # 0 lets CTranslate2 decide
beam_size = 5
vad_filter = true        # drop silence before recognition; avoids phantom phrases
preload_model = true     # load the model when the daemon starts
# model_dir = "~/whisper-models"   # where models are stored (default: the Hugging Face cache)

# input_device = "USB"   # part of the microphone name, or its index (see `voice-input devices`)
max_recording_seconds = 300
min_recording_seconds = 0.3

sound_cues = true
cue_volume = 0.25
notifications = true

# How the text reaches the focused window: auto, uinput, ydotool, wtype, xdotool, clipboard.
insert_method = "auto"
# Who holds the copied text: auto, x11 (also GNOME on Wayland, through XWayland), wl-clipboard.
clipboard = "auto"
# Shift+Insert pastes in browsers, editors and terminals alike.
paste_keys = "shift+insert"
restore_clipboard = false   # put the previous clipboard text back after pasting
trailing_space = true       # so consecutive dictations do not run together

log_level = "INFO"

# GNOME shortcuts installed by `voice-input setup shortcuts`. An empty string disables one.
[shortcuts]
default = "<Super>t"
en = "<Shift><Super>e"
ru = "<Shift><Super>r"
he = "<Shift><Super>h"
cancel = ""
"""
