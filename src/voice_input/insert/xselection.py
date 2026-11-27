"""Clipboard and primary selection through the X11 protocol (python-xlib).

Used on X11, and on GNOME under Wayland through XWayland. GNOME's compositor does not offer
the Wayland data-control protocol, so ``wl-copy`` from a background process waits for a
keyboard focus it never gets. An X11 client, however, may own a selection without focus, and
GNOME copies X11 selections to Wayland applications. Pasting therefore works in every window.

Owning a selection means answering other clients' requests for its content until someone else
takes it over. A single thread owns the X connection and does that; the public methods hand it
work through a queue.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import select
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

_log = logging.getLogger(__name__)

TEXT_TARGETS: Final = ("UTF8_STRING", "text/plain;charset=utf-8", "STRING", "TEXT", "text/plain")
MAX_BYTES: Final = 256 * 1024  # larger transfers would need the INCR protocol
GET_TIMEOUT: Final = 1.0


class SelectionError(RuntimeError):
    pass


@dataclass
class _Job:
    kind: str  # "set" or "get"
    text: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    result: str | None = None
    error: Exception | None = None


def _open_display(name: str | None) -> Any:
    try:
        from Xlib import display
    except ImportError as exc:  # pragma: no cover - python-xlib is a dependency
        raise SelectionError(f"python-xlib is not installed: {exc}") from None
    try:
        return display.Display(name)
    except Exception as exc:
        raise SelectionError(f"cannot connect to the X server {name or ''}: {exc}") from None


def x11_available(display_name: str | None = None) -> bool:
    if not (display_name or os.environ.get("DISPLAY")):
        return False
    try:
        _open_display(display_name).close()
    except SelectionError:
        return False
    return True


class XSelectionClipboard:
    name = "x11-selection"

    def __init__(
        self,
        display_name: str | None = None,
        *,
        opener: Callable[[str | None], Any] = _open_display,
    ) -> None:
        self._display_name = display_name
        self._opener = opener
        self._jobs: queue.Queue[_Job] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._wake_r, self._wake_w = os.pipe()
        self._started = threading.Event()
        self._start_error: Exception | None = None

    # --- public API (any thread) --------------------------------------------------------

    def set_text(self, text: str) -> None:
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise SelectionError("text too long for the clipboard")
        job = self._submit(_Job("set", text))
        if job.error is not None:
            raise job.error

    def get_text(self) -> str | None:
        try:
            job = self._submit(_Job("get"))
        except SelectionError:
            return None
        return job.result

    def close(self) -> None:
        with contextlib.suppress(OSError):
            os.write(self._wake_w, b"q")

    # --- worker -------------------------------------------------------------------------

    def _submit(self, job: _Job) -> _Job:
        self._ensure_thread()
        self._jobs.put(job)
        os.write(self._wake_w, b"j")
        if not job.done.wait(GET_TIMEOUT + 2.0):
            raise SelectionError("the X selection worker did not answer")
        return job

    def _ensure_thread(self) -> None:
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._started.clear()
                self._start_error = None
                self._thread = threading.Thread(
                    target=self._run, name="voice-input-x11-selection", daemon=True
                )
                self._thread.start()
                self._started.wait(5.0)
            if self._start_error is not None:
                error, self._start_error = self._start_error, None
                self._thread = None
                raise SelectionError(str(error))

    def _run(self) -> None:
        try:
            owner = _Owner(self._opener(self._display_name))
        except Exception as exc:
            self._start_error = exc
            self._started.set()
            return
        self._started.set()
        try:
            self._loop(owner)
        finally:
            owner.close()

    def _loop(self, owner: _Owner) -> None:
        while True:
            owner.process_events()
            readable, _, _ = select.select([owner.fileno(), self._wake_r], [], [], 0.25)
            if self._wake_r in readable:
                signal = os.read(self._wake_r, 64)
                if b"q" in signal:
                    return
            while True:
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                owner.run_job(job)
            owner.expire_requests()


class _Owner:
    """State on the worker thread: the connection, a window, and the text being offered."""

    def __init__(self, display: Any) -> None:
        from Xlib import X, Xatom

        self.X = X
        self.d = display
        self.window = display.screen().root.create_window(0, 0, 1, 1, 0, X.CopyFromParent)
        self.atom = display.intern_atom
        self.selections = {self.atom("CLIPBOARD"): "CLIPBOARD", Xatom.PRIMARY: "PRIMARY"}
        self.clipboard = self.atom("CLIPBOARD")
        self.targets = self.atom("TARGETS")
        self.text_targets = [self.atom(name) for name in TEXT_TARGETS]
        self.utf8 = self.text_targets[0]
        self.atom_type = Xatom.ATOM
        self.out_property = self.atom("VOICE_INPUT_SELECTION")
        self.text = ""
        self.owned: set[int] = set()
        self.pending_get: list[tuple[_Job, float]] = []

    def fileno(self) -> int:
        return int(self.d.fileno())

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.d.close()

    def run_job(self, job: _Job) -> None:
        try:
            if job.kind == "set":
                self.text = job.text
                for selection in self.selections:
                    self.window.set_selection_owner(selection, self.X.CurrentTime)
                self.d.flush()
                owner = self.d.get_selection_owner(self.clipboard)
                if owner != self.window:
                    raise SelectionError("another program kept the clipboard")
                self.owned = set(self.selections)
                job.done.set()
            else:
                if self.clipboard in self.owned:
                    job.result = self.text
                    job.done.set()
                    return
                self.window.convert_selection(
                    self.clipboard, self.utf8, self.out_property, self.X.CurrentTime
                )
                self.d.flush()
                self.pending_get.append((job, time.monotonic() + GET_TIMEOUT))
        except Exception as exc:
            job.error = exc if isinstance(exc, SelectionError) else SelectionError(str(exc))
            job.done.set()

    def expire_requests(self) -> None:
        now = time.monotonic()
        for job, deadline in list(self.pending_get):
            if now > deadline:
                self.pending_get.remove((job, deadline))
                job.done.set()  # result stays None

    def process_events(self) -> None:
        x = self.X
        while self.d.pending_events():
            event = self.d.next_event()
            if event.type == x.SelectionRequest:
                self._answer(event)
            elif event.type == x.SelectionClear:
                self.owned.discard(event.atom)
            elif event.type == x.SelectionNotify:
                self._finish_get(event)

    def _finish_get(self, event: Any) -> None:
        if not self.pending_get:
            return
        job, _ = self.pending_get.pop(0)
        if event.property != self.X.NONE:
            with contextlib.suppress(Exception):
                prop = self.window.get_full_property(self.out_property, self.X.AnyPropertyType)
                if prop is not None:
                    value = prop.value
                    job.result = (
                        value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
                    )
        job.done.set()

    def _answer(self, request: Any) -> None:
        from Xlib.protocol import event as xevent

        prop = request.property if request.property != self.X.NONE else request.target
        if request.selection not in self.owned:
            prop = self.X.NONE
        elif request.target == self.targets:
            request.requestor.change_property(
                prop, self.atom_type, 32, [self.targets, *self.text_targets]
            )
        elif request.target in self.text_targets:
            data = self.text.encode("utf-8")
            kind = request.target if request.target != self.atom("TEXT") else self.utf8
            request.requestor.change_property(prop, kind, 8, data)
        else:
            prop = self.X.NONE  # a target we do not offer
        notify = xevent.SelectionNotify(
            time=request.time,
            requestor=request.requestor,
            selection=request.selection,
            target=request.target,
            property=prop,
        )
        with contextlib.suppress(Exception):
            request.requestor.send_event(notify)
        self.d.flush()
