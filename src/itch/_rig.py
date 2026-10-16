from __future__ import annotations

import contextlib
import functools
import itertools
import secrets
import threading
import time
import warnings
from collections.abc import Callable, Iterable, Mapping
from types import TracebackType
from typing import Literal, Self, TypeVar

from itch import _wire
from itch._errors import (
    DevelopmentBuildWarning,
    ItchError,
    LeaseRequiredError,
    ProtocolMismatchError,
)
from itch._transport import Disconnected, Transport, open_transport

REQUEST_TIMEOUT = 2.0
"""Seconds to wait for each reply."""

CHANNELS = range(1, 17)
"""The Channel numbers, CH1 to CH16 as on the board."""

Position = Literal["on", "off"]
"""A Channel's state. "on" means the contact is closed, like a DIP switch's ON."""

_Reply = TypeVar("_Reply", bound=_wire.ReplyBody)


class Rig:
    """A connected Rig. Get one with `Rig.connect()`, and close it when done.

    ```python
    with Rig.connect("tcp://127.0.0.1:4000") as rig:
        print(rig.label, rig.hardware_id, rig.firmware_version)
        with rig.session():
            rig.set_channel(3, "on")
    ```
    """

    def __init__(self, transport: Transport) -> None:
        """Takes over an open transport and sends `Hello`. Use `Rig.connect()` instead."""
        self._transport = transport
        self._name = transport.name
        self._request_ids = itertools.count(1)
        self._lock = threading.Lock()
        """Serialises requests from the script and the Session heartbeat."""
        self._lease: _Lease | None = None
        """The current session's Lease."""
        try:
            hello = self._request(_wire.Hello(), _wire.HelloReply)
            if hello.protocol != _wire.PROTOCOL:
                raise ProtocolMismatchError(self._name, hello.protocol, _wire.PROTOCOL)
        except BaseException:
            transport.close()
            raise
        self._hello = hello
        self._name = self._label = hello.label

    @classmethod
    def connect(cls, name: str | None = None) -> Self:
        """Connects to a Rig and checks it speaks this itch-py's protocol.

        `name` is `tcp://host:port` for `itch-sim` or a dev-build Rig.
        Warns with `DevelopmentBuildWarning` if the Rig runs a development build.
        """
        rig = cls(open_transport(name))
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

    def session(self) -> Session:
        """Takes the Rig's Lease so this script can change its Channels.

        Use it as `with rig.session():`, or keep the result and call `.release()` when done.
        The session keeps itself alive in the background until released.
        """
        token = _new_token()
        holder = ""
        reply = self._request(
            _wire.AcquireLease(token, takeover=False, holder=holder), _wire.AcquireLeaseReply
        )
        lease = _Lease(token, holder, reply.ttl_ms / 1000 / 3, self._renew)
        self._lease = lease
        return Session(functools.partial(self._release, lease))

    def set_channel(self, channel: int, position: Position) -> None:
        """Turns one Channel on or off. Needs a session."""
        self.set_channels({channel: position})

    def set_channels(self, positions: Mapping[int, Position]) -> None:
        """Turns the listed Channels on or off together, in one write, leaving the rest alone.

        Needs a session.
        """
        mask = values = 0
        for channel, position in positions.items():
            bit = _bit(channel)
            mask |= bit
            if _is_on(position):
                values |= bit
        self._request(_wire.WriteChannels(self._token(), mask, values), _wire.WriteChannelsReply)

    def clear(self) -> None:
        """Turns every Channel off. Needs a session."""
        self._request(_wire.Clear(self._token()), _wire.ClearReply)

    def get_channel(self, channel: int) -> Position:
        """Returns whether the Rig commands a Channel "on" or "off"."""
        return self.get_channels([channel])[channel]

    def get_channels(self, channels: Iterable[int] | None = None) -> dict[int, Position]:
        """Returns `{channel: "on" | "off"}` for the listed Channels, or all 16."""
        wanted = {
            channel: _bit(channel) for channel in (CHANNELS if channels is None else channels)
        }
        state = self._request(_wire.GetChannels(), _wire.GetChannelsReply).state
        return {channel: "on" if state & bit else "off" for channel, bit in wanted.items()}

    def close(self) -> None:
        """Closes the connection, freeing the Rig for the next script. Safe to call twice.

        Releases the session first, if there is one.
        """
        if self._lease is not None:
            with contextlib.suppress(ItchError):
                self._release(self._lease)
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

    def _token(self) -> int:
        """The Lease token for a write. Raises `LeaseRequiredError` outside a session."""
        if self._lease is None:
            raise LeaseRequiredError
        return self._lease.token

    def _renew(self, lease: _Lease) -> None:
        # A failed renewal shows up again on the script's next call, which reports it.
        with contextlib.suppress(ItchError):
            self._request(_wire.RenewLease(lease.token, lease.holder), _wire.RenewLeaseReply)

    def _release(self, lease: _Lease) -> None:
        if not lease.stop():
            return
        if self._lease is lease:
            self._lease = None
        self._request(_wire.ReleaseLease(lease.token), _wire.ReleaseLeaseReply)

    def _request(self, body: _wire.RequestBody, reply: type[_Reply]) -> _Reply:
        """Sends one request and waits for its reply."""
        with self._lock:
            return self._exchange(body, reply)

    def _exchange(self, body: _wire.RequestBody, reply: type[_Reply]) -> _Reply:
        request_id = next(self._request_ids) & 0xFFFF_FFFF
        try:
            self._transport.send(_wire.encode(_wire.Request(request_id, body)))
            deadline = time.monotonic() + REQUEST_TIMEOUT
            while (remaining := deadline - time.monotonic()) > 0:
                payload = self._transport.receive(remaining)
                if payload is None:
                    break
                message = _wire.decode(payload)
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


class Session:
    """Holds a Rig's Lease, so the script can change its Channels, until released.

    Get one with `rig.session()`. A background thread renews the Lease every third of its
    lifetime, so the script may sleep or block for as long as it likes.
    """

    def __init__(self, release: Callable[[], None]) -> None:
        self._release = release

    def release(self) -> None:
        """Gives up the Lease, leaving the Channels as they are. Safe to call twice."""
        self._release()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class _Lease:
    """A session's Lease, renewed by a heartbeat thread until stopped."""

    def __init__(
        self, token: int, holder: str, interval: float, renew: Callable[[_Lease], None]
    ) -> None:
        self.token = token
        self.holder = holder
        self._stopped = threading.Event()
        self._heartbeat = threading.Thread(
            target=self._beat, args=(interval, renew), name="itch-heartbeat", daemon=True
        )
        self._heartbeat.start()

    def stop(self) -> bool:
        """Stops the heartbeat, waiting out a renewal in flight. False if already stopped."""
        if self._stopped.is_set():
            return False
        self._stopped.set()
        self._heartbeat.join()
        return True

    def _beat(self, interval: float, renew: Callable[[_Lease], None]) -> None:
        while not self._stopped.wait(interval):
            renew(self)


def _new_token() -> int:
    """A random non-zero Lease token."""
    while not (token := secrets.randbits(64)):
        pass
    return token


def _bit(channel: int) -> int:
    # `in range` alone would let `True` through as CH1 and `1.0` through as a float.
    if type(channel) is not int or channel not in CHANNELS:
        raise ValueError(f"Channel {channel!r} doesn't exist: a Rig's Channels are 1 to 16.")
    return 1 << (channel - 1)


def _is_on(position: Position) -> bool:
    if position not in ("on", "off"):
        raise ValueError(f'{position!r} isn\'t a Channel position: use "on" or "off".')
    return position == "on"
