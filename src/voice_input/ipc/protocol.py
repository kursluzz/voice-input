"""The daemon's command protocol, version 1.

One request per connection: the client sends a single line of JSON and reads a single line of
JSON back. Requests look like ``{"v": 1, "cmd": "toggle", "language": "ru"}``; ``language`` is
optional (the daemon then uses the configured default) and may be ``"auto"``. Every response
has ``ok`` (bool) and ``message`` (str); most also carry ``state``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from voice_input.languages import Language, parse_language

PROTOCOL_VERSION: Final = 1
MAX_MESSAGE_BYTES: Final = 16 * 1024


class ProtocolError(ValueError):
    pass


class Command(StrEnum):
    PING = "ping"
    STATUS = "status"
    TOGGLE = "toggle"
    START = "start"
    STOP = "stop"
    CANCEL = "cancel"
    SHUTDOWN = "shutdown"


LANGUAGE_COMMANDS: Final = frozenset({Command.TOGGLE, Command.START})


@dataclass(frozen=True)
class Request:
    command: Command
    language: Language | None = None
    use_default_language: bool = True  # no language given: the daemon's configured default

    def encode(self) -> bytes:
        payload: dict[str, Any] = {"v": PROTOCOL_VERSION, "cmd": self.command.value}
        if not self.use_default_language:
            payload["language"] = self.language.value if self.language else "auto"
        return (json.dumps(payload) + "\n").encode("utf-8")


def decode_request(line: bytes) -> Request:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"malformed request: {exc}") from None
    if not isinstance(payload, dict):
        raise ProtocolError("a request must be a JSON object")
    if payload.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {payload.get('v')!r}")
    try:
        command = Command(str(payload.get("cmd")))
    except ValueError:
        raise ProtocolError(f"unknown command {payload.get('cmd')!r}") from None
    raw_language = payload.get("language")
    if raw_language is None:
        return Request(command)
    if command not in LANGUAGE_COMMANDS:
        raise ProtocolError(f"{command.value} does not take a language")
    if not isinstance(raw_language, str):
        raise ProtocolError("language must be a string")
    try:
        language = parse_language(raw_language)
    except ValueError as exc:
        raise ProtocolError(str(exc)) from None
    return Request(command, language, use_default_language=False)


def encode_response(response: dict[str, Any]) -> bytes:
    return (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")


def decode_response(line: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"malformed response: {exc}") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise ProtocolError("a response must be a JSON object with 'ok'")
    return payload


def error_response(message: str) -> dict[str, Any]:
    return {"ok": False, "message": message}
