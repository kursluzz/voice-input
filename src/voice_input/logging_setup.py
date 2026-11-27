"""Logging: one line per record, with ``extra=`` fields appended as ``key=value``.

The text a user dictates is never logged; records carry lengths, languages and timings only.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Final

from voice_input.paths import LOG_FILE_NAME

ROOT_LOGGER: Final = "voice_input"
_MARKER: Final = "_voice_input_handler"

_STANDARD: Final = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "taskName",
}


class KeyValueFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = {
            key: value
            for key, value in vars(record).items()
            if key not in _STANDARD and not key.startswith("_")
        }
        if extras:
            line += " " + " ".join(f"{key}={value!r}" for key, value in sorted(extras.items()))
        return line


def configure_logging(
    level: str, log_dir: Path | None = None, *, console_level: str | None = None
) -> logging.Logger:
    """Configure the ``voice_input`` logger. Calling it again replaces the earlier handlers."""
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        if getattr(handler, _MARKER, False):
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = KeyValueFormatter()

    console = logging.StreamHandler()
    console.setLevel(console_level or level)
    console.setFormatter(formatter)
    setattr(console, _MARKER, True)
    logger.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / LOG_FILE_NAME, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        setattr(file_handler, _MARKER, True)
        logger.addHandler(file_handler)
    return logger
