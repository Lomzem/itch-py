"""One open connection to a Rig: its `Hello`, and each request's exchange with its reply."""

from __future__ import annotations

import contextlib
import dataclasses
import itertools
import logging
import queue
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import Self, TypeVar, cast

from itch import _wire
from itch._errors import (
    DisconnectedError,
    ItchError,
    NotRespondingError,
    ProtocolMismatchError,
    rig_error,
)
from itch._transport import NETWORK_CONNECTIONS, Disconnected, TcpTransport, Transport

REQUEST_TIMEOUT = 2.0
"""Seconds to wait for each reply."""

_LOG_DRAIN_TIMEOUT = 0.05
"""Seconds `close()` waits for Log Events still on their way."""

_Reply = TypeVar("_Reply", bound=_wire.ReplyBody)

_RIG_LOGGER = logging.getLogger("itch.rig")

# Python logging levels for Rig log levels 1 error to 4 debug.
_PYTHON_LEVELS = (logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)


class Connection:
    """An open connection to a Rig that has answered `Hello`. Open one with `Connection.open()`.

    `request()` may be called from several threads: requests take turns. A reader thread
    receives everything the Rig sends, handing each reply to the request waiting for it. The
    Rig's Log Events go to the `itch.rig` logger as they arrive, from a thread of their own, so
    a log handler may use the Rig.
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self.name = transport.name
        """The Rig's name in messages: its Label once it has answered `Hello`."""
        self._request_ids = itertools.count(1)
        self._lock = threading.Lock()
        """Serialises requests from several threads."""
        self._state = threading.Condition()
        """Guards the fields below, shared with the reader thread."""
        self._outstanding: _Outstanding | None = None
        self._disconnect: Exception | None = None
        """Why the connection ended, kept so every later request fails the same way."""
        self._closing = False
        """Set once `close()` starts."""
        self._closed_here = False
        """Set if `close()` ended the connection, rather than the Rig or the transport."""
        self._replaced = False
        """Set if `close()` was because this process connected to the same Rig again."""
        self._network_changed = False
        """Set once the Rig accepts a network change over TCP, after which it may drop the
        connection or go silent as it moves."""
        self._log_level = 0  # Log Events from before SetLogLevel's reply are a backlog.
        self._python_log_level = logging.NOTSET
        """The user's `log_level`: Rig records below it aren't forwarded."""
        self._events: queue.SimpleQueue[tuple[_wire.LogEvent, int] | None] = queue.SimpleQueue()
        """Log Events for the dispatcher, each with the user's level when it arrived."""
        self._reader = threading.Thread(
            target=self._read, name=f"itch reader {self.name}", daemon=True
        )
        self._dispatcher = threading.Thread(
            target=self._dispatch, name=f"itch logs {self.name}", daemon=True
        )
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
            connection._reader.start()
            connection._dispatcher.start()
            try:
                hello = connection.request(_wire.Hello(), _wire.HelloReply)
            except DisconnectedError as err:
                if not isinstance(transport, TcpTransport):
                    raise
                # The simulator refuses a fifth TCP connection by closing it, without saying why.
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
            connection.close()
            raise
        return connection

    @property
    def endpoint(self) -> str:
        """Where the Rig is reached, the same however it was named, such as `/dev/ttyACM0` or
        `tcp://127.0.0.1:4000`."""
        return self._transport.endpoint

    @property
    def hardware_id(self) -> str:
        """The Hardware ID from the Rig's `Hello`, such as `60:55:F9:C0:27:18`."""
        return ":".join(f"{byte:02X}" for byte in self.hello.hardware_id)

    def set_log_level(self, python_level: int | None) -> None:
        """Forwards the Rig's log messages at `python_level` and above, or none if `None`."""
        level = _rig_log_level(python_level)

        def apply() -> None:
            # Run by the reader as it takes the reply, so the Log Events before it, the
            # backlog, meet the old level and every later one the new.
            self._log_level = level
            self._python_log_level = python_level or logging.NOTSET

        with self._lock:
            self._exchange(_wire.SetLogLevel(level), _wire.SetLogLevelReply, apply)

    def request(
        self, body: _wire.RequestBody, reply: type[_Reply], *, changes_network: bool = False
    ) -> _Reply:
        """Sends `body` and returns its reply, sending it once more if the Rig stays silent,
        unless the Rig has accepted a network change over TCP.

        Raises the `ItchError` for the Rig's error reply, `NotRespondingError` if it stays
        silent, `DisconnectedError` if the connection fails or has failed, and `ItchError` for
        a malformed reply.

        `changes_network` marks `body` as changing the Rig's network settings. Once the Rig
        accepts it over TCP, the connection is expected to end: a later drop, or silence, raises
        `DisconnectedError` saying to reconnect after the network change.
        """
        on_reply = None
        if changes_network and isinstance(self._transport, TcpTransport):
            on_reply = self._mark_network_changed
        with self._lock:
            return self._exchange(body, reply, on_reply)

    def close(self, *, replaced: bool = False) -> None:
        """Forwards the Log Events still on their way, then closes. Safe to call twice.

        Stops and joins the reader and the dispatcher, unless called from one of them.
        `replaced` says it closes because this process connected to the same Rig again, which
        later requests then say, even if the connection had already dropped.
        """
        with self._state:
            self._replaced = self._replaced or replaced
            if self._closing:
                return
            self._closing = True
            logs_on = self._log_level > 0 and self._disconnect is None
        try:
            if logs_on:
                time.sleep(_LOG_DRAIN_TIMEOUT)  # The reader takes in what is on its way.
            with self._state:
                self._log_level = 0  # The reader queues no more Log Events.
            self._events.put(None)
            self._join(self._dispatcher)  # Its handlers may still use the Rig.
        finally:
            with self._state:
                if self._disconnect is None:
                    self._disconnect = Disconnected("closed")
                    self._closed_here = True
                self._state.notify_all()
            self._transport.stop()  # Wakes the reader.
            self._join(self._reader)
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
        self,
        body: _wire.RequestBody,
        reply: type[_Reply],
        on_reply: Callable[[], None] | None = None,
    ) -> _Reply:
        """Sends `body` up to twice, or once after a network change. Call it holding `_lock`.

        `on_reply` runs on the reader thread as it takes the reply, before it reads on.
        """
        with self._state:
            # A Rig silent since a network change has moved, so sending again only waits.
            attempts = 1 if self._network_changed else 2
        for _ in range(attempts):
            if (answer := self._attempt(body, reply, on_reply)) is not None:
                return answer
        with self._state:
            if self._network_changed:  # The Rig moved without closing the connection.
                if self._disconnect is None:
                    self._disconnect = Disconnected("silent since the network change")
                self._raise_if_disconnected()
        raise NotRespondingError(self.name)

    def _attempt(
        self,
        body: _wire.RequestBody,
        reply: type[_Reply],
        on_reply: Callable[[], None] | None,
    ) -> _Reply | None:
        """Sends `body` once and returns its reply, or `None` after `REQUEST_TIMEOUT`."""
        request_id = next(self._request_ids) & 0xFFFF_FFFF
        outstanding = _Outstanding(request_id, body, reply, on_reply)
        with self._state:
            self._raise_if_disconnected()
            self._outstanding = outstanding
        try:
            try:
                self._transport.send(_wire.encode(_wire.Request(request_id, body)))
            except Disconnected as err:
                self._disconnected(err)
            with self._state:
                self._state.wait_for(
                    lambda: outstanding.done or self._disconnect is not None, REQUEST_TIMEOUT
                )
                self._outstanding = None  # A late reply now answers nothing.
                if outstanding.error is not None:
                    raise outstanding.error
                if outstanding.done:
                    return cast(_Reply, outstanding.reply)
                self._raise_if_disconnected()
                return None
        finally:
            with self._state:
                self._outstanding = None  # Also when sending fails or is interrupted.

    def _raise_if_disconnected(self) -> None:
        """Raises `DisconnectedError` once the connection has ended. Call it holding `_state`."""
        if self._disconnect is not None:
            raise DisconnectedError(
                self.name,
                network_changed=self._network_changed,
                closed=self._closed_here,
                replaced=self._replaced,
            ) from self._disconnect

    def _mark_network_changed(self) -> None:
        """Expects the connection to end. Run by the reader, holding `_state`, as it takes the
        reply to a network change."""
        self._network_changed = True

    def _disconnected(self, err: Exception) -> None:
        """Remembers that the connection ended, and wakes the request waiting on it."""
        with self._state:
            if self._disconnect is None:
                self._disconnect = err
            self._state.notify_all()

    def _read(self) -> None:
        """The reader thread: receives every payload until `close()` or a disconnect."""
        try:
            while True:
                payload = self._transport.receive()
                with self._state:
                    self._route(payload)
        except Exception as err:  # Disconnected, or a bug that mustn't leave a request waiting.
            self._disconnected(err)

    def _route(self, payload: bytes) -> None:
        """Hands a reply to the request waiting for it, and Log Events to the dispatcher.

        Call it holding `_state`. Replies to no request, or to an earlier one, are dropped, and
        so is a malformed payload while no request waits.
        """
        outstanding = self._outstanding
        if outstanding is not None and outstanding.done:
            outstanding = None
        try:
            message = self._decode(payload, outstanding)
            if isinstance(message, _wire.LogEvent):
                if message.level <= self._log_level:
                    self._events.put((message, self._python_log_level))
                return
            if (
                outstanding is None
                or not isinstance(message, _wire.OkResponse | _wire.ErrorResponse)
                or message.request_id != outstanding.request_id
            ):
                return  # Not a reply, or a reply to an earlier request.
            outstanding.reply = self._answer(outstanding, message)
        except ItchError as err:
            if outstanding is None:
                return
            outstanding.error = err
        outstanding.done = True
        self._state.notify_all()

    def _decode(self, payload: bytes, outstanding: _Outstanding | None) -> _wire.Message:
        """Decodes `payload`. Raises `ItchError` if it's malformed, or answers `Hello` in another
        protocol."""
        if outstanding is not None and isinstance(outstanding.body, _wire.Hello):
            theirs = _wire.hello_protocol(payload, outstanding.request_id)
            if theirs not in (None, _wire.PROTOCOL):
                raise ProtocolMismatchError(self.name, theirs, _wire.PROTOCOL)
        try:
            return _wire.decode(payload)
        except _wire.DecodeError as err:
            raise self._malformed(err) from err

    def _answer(
        self, outstanding: _Outstanding, message: _wire.OkResponse | _wire.ErrorResponse
    ) -> _wire.ReplyBody:
        """The reply `message` gives `outstanding`, raising `ItchError` if it's an error."""
        request = outstanding.body.TYPE.name
        if isinstance(message, _wire.ErrorResponse):
            raise rig_error(self.name, request, message.code, message.detail)
        if not isinstance(message.body, outstanding.reply_type):
            raise self._malformed(f"{type(message.body).__name__} answers {request}")
        if outstanding.on_reply is not None:
            outstanding.on_reply()
        return message.body

    def _malformed(self, problem: object) -> ItchError:
        return ItchError(f"Rig {self.name} sent a malformed reply: {problem}")

    def _dispatch(self) -> None:
        """The dispatcher thread: logs each Log Event until `close()` queues `None`."""
        while (item := self._events.get()) is not None:
            event, python_level = item
            with contextlib.suppress(Exception):  # As `logging` does, keep going.
                self._forward(event, python_level)

    def _forward(self, event: _wire.LogEvent, python_level: int) -> None:
        """Logs `event` to `itch.rig`, with the user's level when it arrived."""
        if event.dropped and python_level <= logging.WARNING:
            _RIG_LOGGER.warning("Rig %s dropped %d log messages", self.name, event.dropped)
        if (level := _PYTHON_LEVELS[event.level - 1]) >= python_level:
            _RIG_LOGGER.log(level, "Rig %s: %s", self.name, event.text)

    def _join(self, thread: threading.Thread) -> None:
        """Waits for `thread` to end, unless it is the caller or hasn't started."""
        if thread.ident is not None and thread is not threading.current_thread():
            thread.join()


@dataclasses.dataclass
class _Outstanding:
    """The one request waiting for its reply, which the reader fills in."""

    request_id: int
    body: _wire.RequestBody
    reply_type: type[_wire.ReplyBody]
    on_reply: Callable[[], None] | None
    done: bool = False
    reply: _wire.ReplyBody | None = None
    error: ItchError | None = None


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
