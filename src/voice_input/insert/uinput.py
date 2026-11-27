"""A virtual keyboard through the Linux ``uinput`` module, in pure Python.

Works under every Wayland compositor (GNOME included) and under X11, because the key presses
come from the kernel like those of a real keyboard. Opening ``/dev/uinput`` needs permission;
``voice-input setup uinput`` explains the one-time udev rule.

The device is created once and kept open, because a compositor needs a moment to notice a new
keyboard before it accepts its keys.
"""

from __future__ import annotations

import fcntl
import logging
import os
import struct
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from voice_input.insert.keys import KEY_CODES, KeyCombo

_log = logging.getLogger(__name__)

UINPUT_PATH: Final = Path("/dev/uinput")

# ioctl numbers from linux/uinput.h (_IOW('U', nr, size) and _IO('U', nr)).
UI_SET_EVBIT: Final = 0x40045564
UI_SET_KEYBIT: Final = 0x40045565
UI_DEV_SETUP: Final = 0x405C5503  # struct uinput_setup is 92 bytes
UI_DEV_CREATE: Final = 0x5501
UI_DEV_DESTROY: Final = 0x5502

EV_SYN: Final = 0
EV_KEY: Final = 1
SYN_REPORT: Final = 0
BUS_VIRTUAL: Final = 0x06

DEVICE_NAME: Final = b"voice-input virtual keyboard"
_SETUP_FORMAT: Final = "HHHH80sI"  # struct input_id, name[80], ff_effects_max
_EVENT_FORMAT: Final = "llHHi"  # struct timeval, type, code, value

assert struct.calcsize(_SETUP_FORMAT) == 92
assert struct.calcsize(_EVENT_FORMAT) == 24


class UinputError(RuntimeError):
    pass


def uinput_writable(path: Path = UINPUT_PATH) -> bool:
    return os.access(path, os.W_OK)


class UinputKeyboard:
    name = "uinput"

    def __init__(
        self,
        path: Path = UINPUT_PATH,
        *,
        key_delay: float = 0.012,
        settle_delay: float = 0.3,
        os_open: Callable[[str, int], int] = os.open,
        ioctl: Callable[[int, int, Any], Any] = fcntl.ioctl,
        write: Callable[[int, bytes], int] = os.write,
        close: Callable[[int], None] = os.close,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._path = path
        self._key_delay = key_delay
        self._settle_delay = settle_delay
        self._os_open = os_open
        self._ioctl = ioctl
        self._write = write
        self._close = close
        self._sleep = sleep
        self._fd: int | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        """Create the virtual device now (otherwise on the first key press)."""
        with self._lock:
            self._ensure_open()

    def _ensure_open(self) -> int:
        if self._fd is not None:
            return self._fd
        try:
            fd = self._os_open(str(self._path), os.O_WRONLY | os.O_NONBLOCK)
        except PermissionError:
            raise UinputError(
                f"no permission to use {self._path}; run `voice-input setup uinput` for the fix"
            ) from None
        except FileNotFoundError:
            raise UinputError(
                f"{self._path} does not exist; load the module with: sudo modprobe uinput"
            ) from None
        try:
            self._ioctl(fd, UI_SET_EVBIT, EV_KEY)
            for code in sorted(set(KEY_CODES.values())):
                self._ioctl(fd, UI_SET_KEYBIT, code)
            setup = struct.pack(_SETUP_FORMAT, BUS_VIRTUAL, 0x5649, 0x0001, 1, DEVICE_NAME, 0)
            self._ioctl(fd, UI_DEV_SETUP, setup)
            self._ioctl(fd, UI_DEV_CREATE, 0)
        except OSError as exc:
            self._close(fd)
            raise UinputError(f"cannot create the virtual keyboard: {exc}") from None
        self._fd = fd
        _log.info("virtual keyboard created")
        self._sleep(self._settle_delay)
        return fd

    def _emit(self, fd: int, kind: int, code: int, value: int) -> None:
        self._write(fd, struct.pack(_EVENT_FORMAT, 0, 0, kind, code, value))

    def _key(self, fd: int, code: int, value: int) -> None:
        self._emit(fd, EV_KEY, code, value)
        self._emit(fd, EV_SYN, SYN_REPORT, 0)

    def press(self, combo: KeyCombo) -> None:
        with self._lock:
            fd = self._ensure_open()
            try:
                for code in combo.modifiers:
                    self._key(fd, code, 1)
                    self._sleep(self._key_delay)
                self._key(fd, combo.key, 1)
                self._sleep(self._key_delay)
                self._key(fd, combo.key, 0)
                for code in reversed(combo.modifiers):
                    self._sleep(self._key_delay)
                    self._key(fd, code, 0)
            except OSError as exc:
                raise UinputError(f"cannot send keys: {exc}") from None

    def close(self) -> None:
        with self._lock:
            if self._fd is None:
                return
            fd, self._fd = self._fd, None
            try:
                self._ioctl(fd, UI_DEV_DESTROY, 0)
            except OSError:
                pass
            finally:
                self._close(fd)
