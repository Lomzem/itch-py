"""One open connection to a Rig: its `Hello`, and each request's exchange with its reply."""

from __future__ import annotations

import contextlib
import itertools
import logging
import threading
import time
from types import TracebackType
from typing import Self, TypeVar

from itch import _wire
from itch._errors import (
    DisconnectedError,
    ItchError,
    NotRespondingError,
    ProtocolMismatchError,
    rig_error,
)
from itch._transport import Disconnected, TcpTransport, Transport

REQUEST_TIMEOUT = 2.0
"""Seconds to wait for each reply."""

NETWORK_CONNECTIONS = 4
"""How many TCP connections a Rig serves at once, beside USB."""

_LOG_DRAIN_TIMEOUT = 0.05
"""Seconds `close()` waits for Log Events still on their way."""

_Reply = TypeVar("_Reply", bound=_wire.ReplyBody)

_RIG_LOGGER = logging.getLogger("itch.rig")

# Python logging levels for Rig log levels 1 error to 4 debug.
_PYTHON_LEVELS = (logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)


class Connection:
    """An open connection to a Rig that has answered `Hello`. Open one with `Connection.open()`.

    `request()` may be called from several threads: requests take turns. The Rig's Log Events
    go to the `itch.rig` logger after each reply, outside that turn, and when it closes.
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self.name = transport.name
        """The Rig's name in messages: its Label once it has answered `Hello`."""
        self._request_ids = itertools.count(1)
        self._lock = threading.Lock()
        """Serialises requests from several threads."""
        self._log_level = 0  # Log Events from before SetLogLevel's reply are a backlog.
        self._python_log_level = logging.NOTSET
        """The user's `log_level`: Rig records below it aren't forwarded."""
        self.hello: _wire.HelloReply

    @classmethod
    def open(
        cls,
        transport: Transport,
        *,
        hardware_id: str | None = None,
        log_level: int | None = None,
    ) -> Self:
        """Takes over an open transport, sends `Hello` and sets the Rig's log level.

        Raises `ProtocolMismatchError` if the Rig speaks another protocol, even one whose
        `Hello` this itch-py can't decode, and `ItchError` if `hardware_id` is given and the
        Rig's `Hello` names another, or if a Rig on the network closes the connection before
        answering `Hello`. Closes the transport if it raises.
        """
        connection = cls(transport)
        try:
            try:
                hello = connection.request(_wire.Hello(), _wire.HelloReply)
            except DisconnectedError as err:
                if not isinstance(transport, TcpTransport):
                    raise
                # A Rig refuses a fifth TCP connection by closing it, without saying why.
                raise ItchError(
                    f"Rig at {transport.name} closed the connection before replying to Hello; "
                    f"it may already have {NETWORK_CONNECTIONS} network connections."
                ) from err
            connection.hello = hello
            if hardware_id is not None and not same_hardware_id(
                connection.hardware_id, hardware_id
            ):
                raise ItchError(
                    f"The Rig on {transport.name} says its Hardware ID is "
                    f"{connection.hardware_id}, but its USB port says {hardware_id}; tell the dev."
                )
            connection.name = hello.label
            connection.set_log_level(log_level)
        except BaseException:
            transport.close()
            raise
        return connection

    @property
    def hardware_id(self) -> str:
        """The Hardware ID from the Rig's `Hello`, such as `60:55:F9:C0:27:18`."""
        return ":".join(f"{byte:02X}" for byte in self.hello.hardware_id)

    def set_log_level(self, python_level: int | None) -> None:
        """Forwards the Rig's log messages at `python_level` and above, or none if `None`."""
        level = _rig_log_level(python_level)
        self.request(_wire.SetLogLevel(level), _wire.SetLogLevelReply)
        self._log_level = level
        self._python_log_level = python_level or logging.NOTSET

    def request(self, body: _wire.RequestBody, reply: type[_Reply]) -> _Reply:
        """Sends `body` and returns its reply, sending it once more if the Rig stays silent.

        Raises the `ItchError` for the Rig's error reply, `NotRespondingError` if it stays
        silent, `DisconnectedError` if the connection fails, and `ItchError` for a malformed
        reply.
        """
        events: list[_wire.LogEvent] = []
        try:
            with self._lock:
                return self._exchange(body, reply, events)
        finally:
            self._forward(events)

    def close(self) -> None:
        """Forwards the Log Events still on their way, then closes. Safe to call twice."""
        events: list[_wire.LogEvent] = []
        if self._log_level:
            with self._lock, contextlib.suppress(Disconnected, _wire.DecodeError):
                self._receive_pending(events)
        try:
            self._forward(events)
        finally:
            self._log_level = 0
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

    def _exchange(
        self, body: _wire.RequestBody, reply: type[_Reply], events: list[_wire.LogEvent]
    ) -> _Reply:
        try:
            for _ in range(2):
                if (answer := self._attempt(body, reply, events)) is not None:
                    return answer
        except Disconnected as err:
            raise DisconnectedError from err
        except _wire.DecodeError as err:
            raise ItchError(f"Rig {self.name} sent a malformed reply: {err}") from err
        raise NotRespondingError(self.name)

    def _attempt(
        self, body: _wire.RequestBody, reply: type[_Reply], events: list[_wire.LogEvent]
    ) -> _Reply | None:
        """Sends `body` once and returns its reply, or `None` after `REQUEST_TIMEOUT`."""
        request_id = next(self._request_ids) & 0xFFFF_FFFF
        self._transport.send(_wire.encode(_wire.Request(request_id, body)))
        deadline = time.monotonic() + REQUEST_TIMEOUT
        while (remaining := deadline - time.monotonic()) > 0:
            payload = self._transport.receive(remaining)
            if payload is None:
                break
            if isinstance(body, _wire.Hello):
                theirs = _wire.hello_protocol(payload, request_id)
                if theirs not in (None, _wire.PROTOCOL):
                    raise ProtocolMismatchError(self.name, theirs, _wire.PROTOCOL)
            message = _wire.decode(payload)
            if isinstance(message, _wire.LogEvent):
                events.append(message)
                continue
            if (
                not isinstance(message, _wire.OkResponse | _wire.ErrorResponse)
                or message.request_id != request_id
            ):
                continue  # Not a reply, or a reply to an earlier request.
            if isinstance(message, _wire.ErrorResponse):
                raise rig_error(self.name, body.TYPE.name, message.code, message.detail)
            if not isinstance(message.body, reply):
                raise _wire.DecodeError(f"{type(message.body).__name__} answers {body.TYPE.name}")
            return message.body
        return None

    def _receive_pending(self, events: list[_wire.LogEvent]) -> None:
        """Collects the Log Events that arrived after the last reply."""
        deadline = time.monotonic() + _LOG_DRAIN_TIMEOUT
        while (remaining := deadline - time.monotonic()) > 0:
            payload = self._transport.receive(remaining)
            if payload is None:
                return
            if isinstance(message := _wire.decode(payload), _wire.LogEvent):
                events.append(message)

    def _forward(self, events: list[_wire.LogEvent]) -> None:
        """Logs `events` to `itch.rig`. Called outside the lock, so a handler may use the Rig."""
        for event in events:
            if event.level > self._log_level:
                continue
            if event.dropped and self._python_log_level <= logging.WARNING:
                _RIG_LOGGER.warning("Rig %s dropped %d log messages", self.name, event.dropped)
            if (level := _PYTHON_LEVELS[event.level - 1]) >= self._python_log_level:
                _RIG_LOGGER.log(level, "Rig %s: %s", self.name, event.text)


def same_hardware_id(a: str, b: str) -> bool:
    """Whether two Hardware IDs match, ignoring case and `:` or `-` separators."""

    def bare(hardware_id: str) -> str:
        return hardware_id.replace(":", "").replace("-", "").casefold()

    return bare(a) == bare(b)


def _rig_log_level(python_level: int | None) -> int:
    """The quietest Rig log level that still sends everything at `python_level` and above."""
    if python_level is None:
        return 0
    for rig_level in (4, 3, 2):
        if python_level <= _PYTHON_LEVELS[rig_level - 1]:
            return rig_level
    return 1
