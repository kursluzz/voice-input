"""GNOME custom keyboard shortcuts, managed with ``gsettings``.

Each Voice Input action gets its own entry under the custom-keybindings path, named
``voice-input-<action>``, so installing again updates the entries in place and removing them
leaves the user's other shortcuts alone.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from voice_input.config import Shortcut
from voice_input.system import CommandFailedError, Runner, run

MEDIA_KEYS: Final = "org.gnome.settings-daemon.plugins.media-keys"
LIST_KEY: Final = "custom-keybindings"
CUSTOM_SCHEMA: Final = f"{MEDIA_KEYS}.custom-keybinding"
BASE_PATH: Final = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
PATH_PREFIX: Final = BASE_PATH + "voice-input-"

# Schemas that hold the desktop's own shortcuts; checked for conflicts.
SYSTEM_SCHEMAS: Final = (
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.shell.keybindings",
    "org.gnome.mutter.keybindings",
    "org.gnome.mutter.wayland.keybindings",
    MEDIA_KEYS,
)

_STRING: Final = re.compile(r"'((?:[^'\\]|\\.)*)'")
_MODIFIER: Final = re.compile(r"<([^>]+)>")
_MODIFIER_ALIASES: Final = {
    "primary": "ctrl",
    "control": "ctrl",
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "mod1": "alt",
    "super": "super",
    "mod4": "super",
    "meta": "meta",
    "hyper": "hyper",
}


def path_for(action: Shortcut) -> str:
    return f"{PATH_PREFIX}{action.value}/"


def parse_string_list(text: str) -> list[str]:
    """Parse a GVariant string array as printed by ``gsettings get`` (``@as []`` included)."""
    return [match.replace("\\'", "'").replace("\\\\", "\\") for match in _STRING.findall(text)]


def format_string_list(items: list[str]) -> str:
    escaped = (item.replace("\\", "\\\\").replace("'", "\\'") for item in items)
    return "[" + ", ".join(f"'{item}'" for item in escaped) + "]"


def normalize_binding(binding: str) -> tuple[frozenset[str], str] | None:
    """``<Shift><Super>e`` and ``<Super><Shift>E`` compare equal. None for an empty binding."""
    binding = binding.strip()
    if not binding or binding.lower() == "disabled":
        return None
    modifiers = frozenset(
        _MODIFIER_ALIASES.get(name.lower(), name.lower()) for name in _MODIFIER.findall(binding)
    )
    key = _MODIFIER.sub("", binding).strip().lower()
    return modifiers, key


@dataclass(frozen=True)
class PlannedShortcut:
    action: Shortcut
    binding: str
    command: str
    name: str


def plan(shortcuts: Mapping[Shortcut, str], executable: str) -> list[PlannedShortcut]:
    """The shortcuts to install, skipping actions whose binding is empty."""
    planned: list[PlannedShortcut] = []
    for action in Shortcut:
        binding = shortcuts.get(action, "").strip()
        if not binding:
            continue
        if action is Shortcut.DEFAULT:
            command, name = f"{executable} toggle", "Voice Input: dictate (default language)"
        elif action is Shortcut.CANCEL:
            command, name = f"{executable} cancel", "Voice Input: cancel"
        else:
            command = f"{executable} toggle --lang {action.value}"
            name = f"Voice Input: dictate ({action.value})"
        planned.append(PlannedShortcut(action, binding, command, name))
    return planned


class GnomeShortcuts:
    def __init__(self, runner: Runner = run) -> None:
        self._run = runner

    def _gsettings(self, *args: str) -> str:
        result = self._run(["gsettings", *args])
        if result.returncode != 0:
            raise CommandFailedError(
                f"gsettings {' '.join(args[:2])} failed: {result.stderr.strip()}"
            )
        return result.stdout.strip()

    def available(self) -> bool:
        try:
            self._gsettings("get", MEDIA_KEYS, LIST_KEY)
        except Exception:
            return False
        return True

    def custom_paths(self) -> list[str]:
        return parse_string_list(self._gsettings("get", MEDIA_KEYS, LIST_KEY))

    def _set_paths(self, paths: list[str]) -> None:
        self._gsettings("set", MEDIA_KEYS, LIST_KEY, format_string_list(paths))

    def _custom(self, path: str) -> str:
        return f"{CUSTOM_SCHEMA}:{path}"

    def installed(self) -> dict[str, tuple[str, str]]:
        """``{path: (binding, command)}`` for the Voice Input entries."""
        result: dict[str, tuple[str, str]] = {}
        for path in self.custom_paths():
            if path.startswith(PATH_PREFIX):
                binding = parse_string_list(self._gsettings("get", self._custom(path), "binding"))
                command = parse_string_list(self._gsettings("get", self._custom(path), "command"))
                result[path] = (binding[0] if binding else "", command[0] if command else "")
        return result

    def conflicts(self, binding: str) -> list[str]:
        """Descriptions of other shortcuts that use ``binding``."""
        wanted = normalize_binding(binding)
        if wanted is None:
            return []
        found: list[str] = []
        for schema in SYSTEM_SCHEMAS:
            try:
                listing = self._gsettings("list-recursively", schema)
            except Exception:
                continue
            for line in listing.splitlines():
                parts = line.split(" ", 2)
                if len(parts) < 3:
                    continue
                values = parse_string_list(parts[2])
                if any(normalize_binding(value) == wanted for value in values):
                    found.append(f"{parts[0]} {parts[1]}")
        for path in self.custom_paths():
            if path.startswith(PATH_PREFIX):
                continue
            values = parse_string_list(self._gsettings("get", self._custom(path), "binding"))
            if any(normalize_binding(value) == wanted for value in values):
                name = parse_string_list(self._gsettings("get", self._custom(path), "name"))
                found.append(f"custom shortcut {name[0] if name else path!r}")
        return found

    def install(self, planned: list[PlannedShortcut]) -> None:
        wanted = {path_for(item.action) for item in planned}
        paths = self.custom_paths()
        # Drop our entries that are no longer wanted (for example a binding set to "").
        for path in [p for p in paths if p.startswith(PATH_PREFIX) and p not in wanted]:
            self._reset(path)
        paths = [p for p in paths if not p.startswith(PATH_PREFIX) or p in wanted]
        for item in planned:
            path = path_for(item.action)
            custom = self._custom(path)
            self._gsettings("set", custom, "name", item.name)
            self._gsettings("set", custom, "command", item.command)
            self._gsettings("set", custom, "binding", item.binding)
            if path not in paths:
                paths.append(path)
        self._set_paths(paths)

    def _reset(self, path: str) -> None:
        for key in ("name", "command", "binding"):
            self._gsettings("reset", self._custom(path), key)

    def remove(self) -> list[str]:
        paths = self.custom_paths()
        ours = [p for p in paths if p.startswith(PATH_PREFIX)]
        for path in ours:
            self._reset(path)
        self._set_paths([p for p in paths if not p.startswith(PATH_PREFIX)])
        return ours
