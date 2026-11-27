"""Voice Input: offline voice typing for the Linux desktop."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("voice-input")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
