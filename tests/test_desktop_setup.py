from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from voice_input.config import DEFAULT_SHORTCUTS, Shortcut
from voice_input.desktop import udev
from voice_input.desktop.gnome import (
    BASE_PATH,
    CUSTOM_SCHEMA,
    MEDIA_KEYS,
    GnomeShortcuts,
    format_string_list,
    normalize_binding,
    parse_string_list,
    path_for,
    plan,
)
from voice_input.desktop.systemd import UserService, render_unit, unit_path
from voice_input.system import CommandFailedError, CommandResult

# --- GVariant lists and bindings -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "items"),
    [
        ("@as []", []),
        ("['/a/', '/b/']", ["/a/", "/b/"]),
        ("['it\\'s']", ["it's"]),
    ],
)
def test_parse_string_list(text: str, items: list[str]) -> None:
    assert parse_string_list(text) == items


def test_format_string_list_round_trips() -> None:
    items = ["/a/", "it's", "back\\slash"]
    assert parse_string_list(format_string_list(items)) == items
    assert format_string_list([]) == "[]"


def test_normalize_binding() -> None:
    assert normalize_binding("<Shift><Super>e") == normalize_binding("<Super><Shift>E")
    assert normalize_binding("<Primary>v") == normalize_binding("<Control>v")
    assert normalize_binding("<Super>t") != normalize_binding("<Super><Shift>t")
    assert normalize_binding("") is None
    assert normalize_binding("disabled") is None


def test_plan_builds_commands_and_skips_empty_bindings() -> None:
    planned = plan(DEFAULT_SHORTCUTS, "/home/u/.local/bin/voice-input")
    by_action = {item.action: item for item in planned}
    assert Shortcut.CANCEL not in by_action  # empty by default
    assert by_action[Shortcut.DEFAULT].command == "/home/u/.local/bin/voice-input toggle"
    assert by_action[Shortcut.RU].command == "/home/u/.local/bin/voice-input toggle --lang ru"
    assert by_action[Shortcut.HE].binding == "<Shift><Super>h"

    with_cancel = plan({**DEFAULT_SHORTCUTS, Shortcut.CANCEL: "<Super>Escape"}, "vi")
    assert any(item.command == "vi cancel" for item in with_cancel)


# --- gsettings fake ------------------------------------------------------------------------


@dataclass
class FakeGsettings:
    """A tiny in-memory dconf that understands the gsettings calls we make."""

    values: dict[tuple[str, str], str] = field(default_factory=dict)
    listings: dict[str, str] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.values.setdefault((MEDIA_KEYS, "custom-keybindings"), "@as []")

    def __call__(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        capture: bool = True,
        timeout: float = 5.0,
    ) -> CommandResult:
        argv = list(args)
        self.calls.append(argv)
        assert argv[0] == "gsettings"
        verb = argv[1]
        if verb == "get":
            value = self.values.get((argv[2], argv[3]), "''")
            return CommandResult(0, value + "\n")
        if verb == "set":
            value = argv[4]
            if argv[3] != "custom-keybindings":
                value = format_string_list([value])
            self.values[(argv[2], argv[3])] = value
            return CommandResult(0)
        if verb == "reset":
            self.values.pop((argv[2], argv[3]), None)
            return CommandResult(0)
        if verb == "list-recursively":
            return CommandResult(0, self.listings.get(argv[2], ""))
        return CommandResult(1, "", "unknown verb")

    def paths(self) -> list[str]:
        return parse_string_list(self.values[(MEDIA_KEYS, "custom-keybindings")])


OTHER = BASE_PATH + "custom0/"


def test_install_adds_entries_and_keeps_other_shortcuts() -> None:
    fake = FakeGsettings({(MEDIA_KEYS, "custom-keybindings"): format_string_list([OTHER])})
    shortcuts = GnomeShortcuts(fake)
    shortcuts.install(plan(DEFAULT_SHORTCUTS, "vi"))
    assert fake.paths()[0] == OTHER
    assert set(fake.paths()[1:]) == {
        path_for(Shortcut.DEFAULT),
        path_for(Shortcut.EN),
        path_for(Shortcut.RU),
        path_for(Shortcut.HE),
    }
    installed = shortcuts.installed()
    assert installed[path_for(Shortcut.RU)] == ("<Shift><Super>r", "vi toggle --lang ru")
    assert installed[path_for(Shortcut.DEFAULT)] == ("<Super>t", "vi toggle")


def test_install_twice_is_idempotent_and_drops_disabled_actions() -> None:
    fake = FakeGsettings()
    shortcuts = GnomeShortcuts(fake)
    shortcuts.install(plan(DEFAULT_SHORTCUTS, "vi"))
    shortcuts.install(plan({**DEFAULT_SHORTCUTS, Shortcut.HE: ""}, "vi"))
    assert len(fake.paths()) == 3
    assert path_for(Shortcut.HE) not in fake.paths()
    assert (f"{CUSTOM_SCHEMA}:{path_for(Shortcut.HE)}", "binding") not in fake.values


def test_remove_only_removes_ours() -> None:
    fake = FakeGsettings({(MEDIA_KEYS, "custom-keybindings"): format_string_list([OTHER])})
    shortcuts = GnomeShortcuts(fake)
    shortcuts.install(plan(DEFAULT_SHORTCUTS, "vi"))
    removed = shortcuts.remove()
    assert len(removed) == 4
    assert fake.paths() == [OTHER]
    assert shortcuts.installed() == {}


def test_conflicts_with_system_and_custom_shortcuts() -> None:
    fake = FakeGsettings(
        {
            (MEDIA_KEYS, "custom-keybindings"): format_string_list([OTHER]),
            (f"{CUSTOM_SCHEMA}:{OTHER}", "binding"): "'<Super><Shift>r'",
            (f"{CUSTOM_SCHEMA}:{OTHER}", "name"): "'Reader'",
        },
        listings={
            "org.gnome.desktop.wm.keybindings": (
                "org.gnome.desktop.wm.keybindings minimize ['<Super>h']\n"
                "org.gnome.desktop.wm.keybindings close ['<Alt>F4']\n"
            )
        },
    )
    shortcuts = GnomeShortcuts(fake)
    assert shortcuts.conflicts("<Super>h") == ["org.gnome.desktop.wm.keybindings minimize"]
    assert shortcuts.conflicts("<Shift><Super>r") == ["custom shortcut 'Reader'"]
    assert shortcuts.conflicts("<Super>t") == []
    assert shortcuts.conflicts("") == []


def test_gsettings_failure_is_reported() -> None:
    def failing(args: Sequence[str], **_: object) -> CommandResult:
        return CommandResult(1, "", "No such schema")

    shortcuts = GnomeShortcuts(failing)
    assert not shortcuts.available()
    with pytest.raises(CommandFailedError, match="No such schema"):
        shortcuts.custom_paths()


# --- systemd -------------------------------------------------------------------------------


def test_unit_path_follows_xdg() -> None:
    assert unit_path({"HOME": "/h"}) == Path("/h/.config/systemd/user/voice-input.service")
    assert unit_path({"HOME": "/h", "XDG_CONFIG_HOME": "/c"}) == Path(
        "/c/systemd/user/voice-input.service"
    )


def test_render_unit() -> None:
    unit = render_unit("/home/u/.local/bin/voice-input")
    assert "ExecStart=/home/u/.local/bin/voice-input daemon" in unit
    assert "WantedBy=graphical-session.target" in unit


@dataclass
class FakeSystemctl:
    calls: list[list[str]] = field(default_factory=list)
    returncode: int = 0
    stdout: str = ""

    def __call__(self, args: Sequence[str], **_: object) -> CommandResult:
        self.calls.append(list(args))
        return CommandResult(self.returncode, self.stdout, "boom" if self.returncode else "")


def test_service_install_and_remove(tmp_path: Path) -> None:
    fake = FakeSystemctl()
    service = UserService(tmp_path / "systemd" / "user" / "voice-input.service", fake)
    service.install("/bin/vi")
    assert "ExecStart=/bin/vi daemon" in service.path.read_text()
    assert fake.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "voice-input.service"],
    ]
    assert service.remove() is True
    assert not service.path.exists()
    assert service.remove() is False


def test_service_install_failure(tmp_path: Path) -> None:
    service = UserService(tmp_path / "u.service", FakeSystemctl(returncode=1))
    with pytest.raises(CommandFailedError, match="boom"):
        service.install("/bin/vi")


def test_service_is_active() -> None:
    assert UserService(Path("/x"), FakeSystemctl(stdout="active\n")).is_active()
    assert not UserService(Path("/x"), FakeSystemctl(returncode=3, stdout="inactive")).is_active()


# --- udev ----------------------------------------------------------------------------------


def test_udev_rule_uses_uaccess_and_sorts_before_seat_late() -> None:
    assert 'TAG+="uaccess"' in udev.RULE
    assert udev.RULE_PATH.name < "73-seat-late.rules"


def test_install_steps_write_rule_through_tee() -> None:
    steps = udev.install_steps()
    assert steps[0].args == ("sudo", "tee", str(udev.RULE_PATH))
    assert steps[0].input_text == udev.RULE
    assert all(step.args[0] == "sudo" for step in steps)
    assert steps[-1].args[-1] == "--name-match=uinput"


def test_shell_script_is_valid_shell(tmp_path: Path) -> None:
    script = udev.shell_script(udev.install_steps() + udev.remove_steps())
    assert "printf '%s'" in script
    result = subprocess.run(["sh", "-n"], input=script, text=True, check=False)
    assert result.returncode == 0
