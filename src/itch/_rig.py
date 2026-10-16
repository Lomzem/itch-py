from __future__ import annotations

import itertools
import logging
import time
import warnings
from types import TracebackType
from typing import Self, TypeVar

from itch import _wire
from itch._errors import DevelopmentBuildWarning, ItchError, ProtocolMismatchError
from itch._transport import Disconnected, Transport, open_transport

REQUEST_TIMEOUT = 2.0
"""Seconds to wait for each reply."""

_Reply = TypeVar("_Reply", bound=_wire.ReplyBody)

_RIG_LOGGER = logging.getLogger("itch.rig")

# Python logging levels for Rig log levels 1 error to 4 debug.
_PYTHON_LEVELS = (logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)


def _rig_log_level(python_level: int | None) -> int:
    """The quietest Rig log level that still sends everything at `python_level` and above."""
    if python_level is None:
        return 0
    for rig_level in (4, 3, 2):
        if python_level <= _PYTHON_LEVELS[rig_level - 1]:
            return rig_level
    return 1


class Rig:
    """A connected Rig. Get one with `Rig.connect()`, and close it when done.

    ```python
    with Rig.connect("tcp://127.0.0.1:4000") as rig:
        print(rig.label, rig.hardware_id, rig.firmware_version)
    ```
    """

    def __init__(self, transport: Transport, *, log_level: int | None = None) -> None:
        """Takes over an open transport and sends `Hello`. Use `Rig.connect()` instead."""
        self._transport = transport
        self._name = transport.name
        self._request_ids = itertools.count(1)
        self._log_level = 0  # Log Events from before SetLogLevel's reply are a backlog.
        try:
            hello = self._request(_wire.Hello(), _wire.HelloReply)
            if hello.protocol != _wire.PROTOCOL:
                raise ProtocolMismatchError(self._name, hello.protocol, _wire.PROTOCOL)
            self._name = hello.label
            level = _rig_log_level(log_level)
            self._request(_wire.SetLogLevel(level), _wire.SetLogLevelReply)
        except BaseException:
            transport.close()
            raise
        self._hello = hello
        self._label = hello.label
        self._log_level = level

    @classmethod
    def connect(cls, name: str | None = None, *, log_level: int | None = None) -> Self:
        """Connects to a Rig and checks it speaks this itch-py's protocol.

        `name` is `tcp://host:port` for `itch-sim` or a dev-build Rig.
        Warns with `DevelopmentBuildWarning` if the Rig runs a development build.

        The Rig's own log messages are off unless you pass `log_level`, such as
        `logging.INFO`. Those at that level and above then go to the `itch.rig` logger
        whenever itch-py hears from the Rig. Configure Python `logging` to see them.
        """
        rig = cls(open_transport(name), log_level=log_level)
        if notes := rig._dev_build_notes:
            try:
                warnings.warn(
                    f"Rig {rig.label} runs a development build ({', '.join(notes)}). "
                    "Have the dev flash a release build before QA use it.",
                    DevelopmentBuildWarning,
                    stacklevel=2,
                )
            except BaseException:
                rig.close()  # The warning was turned into an error.
                raise
        return rig

    @property
    def label(self) -> str:
        """The Rig's Label, such as `itch-C02718`."""
        return self._label

    @property
    def hardware_id(self) -> str:
        """The Rig's Hardware ID, such as `60:55:F9:C0:27:18`."""
        return ":".join(f"{byte:02X}" for byte in self._hello.hardware_id)

    @property
    def firmware_version(self) -> str:
        """The Rig's firmware version, such as `1.0.0`."""
        return self._hello.firmware_version

    def close(self) -> None:
        """Closes the connection, freeing the Rig for the next script. Safe to call twice."""
        self._transport.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Rig {self.label} {self.hardware_id} firmware {self.firmware_version}>"

    @property
    def _dev_build_notes(self) -> list[str]:
        notes: list[str] = []
        if self._hello.features & _wire.FEATURE_WIFI:
            notes.append("WiFi enabled")
        if self._hello.dirty:
            notes.append("built from uncommitted code")
        return notes

    def _forward_log(self, event: _wire.LogEvent) -> None:
        if event.level > self._log_level:
            return
        if event.dropped:
            _RIG_LOGGER.warning("Rig %s dropped %d log messages", self._name, event.dropped)
        _RIG_LOGGER.log(_PYTHON_LEVELS[event.level - 1], "Rig %s: %s", self._name, event.text)

    def _request(self, body: _wire.RequestBody, reply: type[_Reply]) -> _Reply:
        """Sends one request and waits for its reply."""
        request_id = next(self._request_ids) & 0xFFFF_FFFF
        try:
            self._transport.send(_wire.encode(_wire.Request(request_id, body)))
            deadline = time.monotonic() + REQUEST_TIMEOUT
            while (remaining := deadline - time.monotonic()) > 0:
                payload = self._transport.receive(remaining)
                if payload is None:
                    break
                message = _wire.decode(payload)
                if isinstance(message, _wire.LogEvent):
                    self._forward_log(message)
                    continue
                if (
                    not isinstance(message, _wire.OkResponse | _wire.ErrorResponse)
                    or message.request_id != request_id
                ):
                    continue  # Not a reply, or a reply to an earlier request.
                if isinstance(message, _wire.ErrorResponse):
                    raise ItchError(f"Rig {self._name} refused {body.TYPE.name}: {message.detail}")
                if not isinstance(message.body, reply):
                    raise _wire.DecodeError(f"{type(message.body).__name__} answers {body}")
                return message.body
        except Disconnected as err:
            raise ItchError("Rig disconnected; run the script again.") from err
        except _wire.DecodeError as err:
            raise ItchError(f"Rig {self._name} sent a malformed reply: {err}") from err
        raise ItchError(f"Rig {self._name} isn't responding.")
