from __future__ import annotations

import contextlib
import dataclasses
import functools
import getpass
import itertools
import logging
import os
import secrets
import socket
import sys
import threading
import time
import warnings
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, TypeVar

from itch import _wire
from itch._errors import (
    AmbiguousRigError,
    DevelopmentBuildWarning,
    DisconnectedError,
    ItchError,
    LeaseLostError,
    LeaseRequiredError,
    NotRespondingError,
    ProtocolMismatchError,
    RigNotFoundError,
    rig_error,
)
from itch._status import Status, from_reply
from itch._transport import Disconnected, Transport, open_tcp
from itch._usb import PortInUse, UsbPort, UsbTransport, usb_ports

REQUEST_TIMEOUT = 2.0
"""Seconds to wait for each reply."""

_LOG_DRAIN_TIMEOUT = 0.05
"""Seconds `close()` waits for Log Events still on their way."""

CHANNELS = range(1, 17)
"""The Channel numbers, CH1 to CH16 as on the board."""

Position = Literal["on", "off"]
"""A Channel's state. "on" means the contact is closed, like a DIP switch's ON."""

_Reply = TypeVar("_Reply", bound=_wire.ReplyBody)
_Rig = TypeVar("_Rig", bound="Rig")

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
    with Rig.connect("bench3") as rig:
        print(rig.label, rig.hardware_id, rig.firmware_version)
        with rig.session():
            rig.set_channel(3, "on")
    ```
    """

    def __init__(self, transport: Transport, *, log_level: int | None = None) -> None:
        """Takes over an open transport and sends `Hello`. Use `Rig.connect()` instead."""
        self._transport = transport
        self._name = transport.name
        self._request_ids = itertools.count(1)
        self._log_level = 0  # Log Events from before SetLogLevel's reply are a backlog.
        self._lock = threading.Lock()
        """Serialises requests from the script and the Session heartbeat."""
        self._lease: _Lease | None = None
        """The current session's Lease."""
        try:
            hello = self._request(_wire.Hello(), _wire.HelloReply)
            if hello.protocol != _wire.PROTOCOL:
                raise ProtocolMismatchError(self._name, hello.protocol, _wire.PROTOCOL)
            self._name = hello.label
            self._set_log_level(log_level)
        except BaseException:
            transport.close()
            raise
        self._hello = hello
        self._label = hello.label

    @classmethod
    def connect(cls, name: str | None = None, *, log_level: int | None = None) -> Self:
        """Connects to a Rig and checks it speaks this itch-py's protocol.

        `name` picks a Rig plugged in over USB by its port (`COM4`, `/dev/ttyACM0`), its
        Hardware ID (`60:55:F9:C0:27:18`) or its label (`bench3`), ignoring case. Leave it out
        when only one Rig is plugged in. A label lookup skips Rigs other programs have open.
        `tcp://host:port` reaches `itch-sim` or a dev-build Rig.

        Raises `RigNotFoundError` or `AmbiguousRigError`, listing the Rigs found, if `name`
        doesn't pick out one Rig. Warns with `DevelopmentBuildWarning` if the Rig runs a
        development build.

        The Rig's own log messages are off unless you pass `log_level`, such as
        `logging.INFO`. Those at that level and above then go to the `itch.rig` logger
        whenever itch-py hears from the Rig, and when it closes. Configure Python `logging`
        to see them.
        """
        if name is not None and name.startswith("tcp://"):
            rig = cls(open_tcp(name), log_level=log_level)
        else:
            rig = _find(cls, name, log_level)
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

    def session(self, holder: str | None = None, *, takeover: bool = False) -> Session:
        """Takes the Rig's Lease so this script can change its Channels.

        Use it as `with rig.session():`, or keep the result and call `.release()` when done.
        The session keeps itself alive in the background until released.

        `holder` tells colleagues who holds the Rig, at most 64 bytes of UTF-8. It defaults to
        `user@host script.py`. Raises `LeaseHeldError` if someone else holds the Rig; if their
        script is dead, `takeover=True` takes the Rig from them.
        """
        if self._lease is not None:
            raise RuntimeError(
                f"Rig {self._name} already has a session: release it before starting another."
            )
        if holder is None:
            holder = _default_holder()
        elif (size := len(holder.encode())) > _wire.MAX_LABEL:
            raise ValueError(
                f"The holder {holder!r} is {size} bytes, but at most {_wire.MAX_LABEL} bytes fit."
            )
        reply = self._request(
            _wire.AcquireLease(token := _new_token(), takeover, holder), _wire.AcquireLeaseReply
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

    def set_label(self, label: str) -> None:
        """Renames the Rig, at most 64 bytes of UTF-8. Needs a session.

        The Rig keeps the label across reboots. An empty label restores the default, such as
        `itch-C02718`. Raises `StorageFaultError` if the Rig couldn't save it.
        """
        if (size := len(label.encode())) > _wire.MAX_LABEL:
            raise ValueError(
                f"The label {label!r} is {size} bytes, but at most {_wire.MAX_LABEL} bytes fit."
            )
        reply = self._request(_wire.SetLabel(self._token(), label), _wire.SetLabelReply)
        self._label = self._name = reply.label

    def status(self) -> Status:
        """Returns the Rig's uptime, reset reason, last panic, Holder and fault counters."""
        return from_reply(self._request(_wire.GetStatus(), _wire.GetStatusReply))

    def close(self) -> None:
        """Closes the connection, freeing the Rig for the next script. Safe to call twice.

        Releases the session first, if there is one.
        """
        if self._lease is not None:
            with contextlib.suppress(ItchError):
                self._release(self._lease)
        if self._log_level:
            with self._lock, contextlib.suppress(Disconnected, _wire.DecodeError):
                self._forward_pending_logs()
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

    def _set_log_level(self, python_level: int | None) -> None:
        level = _rig_log_level(python_level)
        self._request(_wire.SetLogLevel(level), _wire.SetLogLevelReply)
        self._log_level = level

    def _token(self) -> int:
        """The Lease token for a write.

        Raises `LeaseRequiredError` outside a session, and `LeaseLostError` once the heartbeat
        has seen someone else take the Rig.
        """
        if self._lease is None:
            raise LeaseRequiredError
        if self._lease.lost_to is not None:
            raise LeaseLostError(self._name, self._lease.lost_to)
        return self._lease.token

    def _renew(self, lease: _Lease) -> None:
        try:
            self._request(_wire.RenewLease(lease.token, lease.holder), _wire.RenewLeaseReply)
        except LeaseLostError as err:
            lease.lost_to = err.reason
        except ItchError:
            pass  # A failed renewal shows up again on the script's next call, which reports it.

    def _release(self, lease: _Lease) -> None:
        if not lease.stop():
            return
        if self._lease is lease:
            self._lease = None
        self._request(_wire.ReleaseLease(lease.token), _wire.ReleaseLeaseReply)

    def _forward_pending_logs(self) -> None:
        """Forwards the Log Events that arrived after the last reply."""
        deadline = time.monotonic() + _LOG_DRAIN_TIMEOUT
        while (remaining := deadline - time.monotonic()) > 0:
            payload = self._transport.receive(remaining)
            if payload is None:
                return
            if isinstance(message := _wire.decode(payload), _wire.LogEvent):
                self._forward_log(message)

    def _request(self, body: _wire.RequestBody, reply: type[_Reply]) -> _Reply:
        """Sends one request and waits for its reply."""
        with self._lock:
            return self._exchange(body, reply)

    def _exchange(self, body: _wire.RequestBody, reply: type[_Reply]) -> _Reply:
        """Sends `body`, and once more with a fresh `request_id` if the Rig stays silent."""
        try:
            for _ in range(2):
                if (answer := self._attempt(body, reply)) is not None:
                    return answer
        except Disconnected as err:
            raise DisconnectedError from err
        except _wire.DecodeError as err:
            raise ItchError(f"Rig {self._name} sent a malformed reply: {err}") from err
        raise NotRespondingError(self._name)

    def _attempt(self, body: _wire.RequestBody, reply: type[_Reply]) -> _Reply | None:
        """Sends `body` once and returns its reply, or `None` after `REQUEST_TIMEOUT`."""
        request_id = next(self._request_ids) & 0xFFFF_FFFF
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
                raise rig_error(self._name, body.TYPE.name, message.code, message.detail)
            if not isinstance(message.body, reply):
                raise _wire.DecodeError(f"{type(message.body).__name__} answers {body}")
            return message.body
        return None


class Session:
    """Holds a Rig's Lease, so the script can change its Channels, until released.

    Get one with `rig.session()`. A background thread renews the Lease every third of its
    lifetime, so the script may sleep or block for as long as it likes.

    If someone takes the Rig over, the script's next change raises `LeaseLostError`.
    Leaving the `with` block never does.
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
        self.lost_to: str | None = None
        """Who took the Rig, once the heartbeat has seen it go."""
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
        while self.lost_to is None and not self._stopped.wait(interval):
            renew(self)


@dataclasses.dataclass(frozen=True)
class RigInfo:
    """A Rig plugged in over USB, as `list_rigs()` finds it."""

    port: str
    """Such as `COM4` or `/dev/ttyACM0`."""
    hardware_id: str
    """Such as `60:55:F9:C0:27:18`."""
    label: str | None
    """Such as `bench3`, or `None` if the Rig is in use."""
    firmware_version: str | None
    """Such as `1.0.0`, or `None` if the Rig is in use."""

    @property
    def in_use(self) -> bool:
        """Whether another program has the Rig open, so itch-py couldn't ask its label."""
        return self.label is None


def list_rigs() -> list[RigInfo]:
    """The Rigs plugged in over USB.

    Opens each free Rig briefly to ask its label and firmware version. Rigs other programs
    have open are listed as in use, without disturbing them.
    """
    return [_info(Rig, port) for port in usb_ports()]


def rig_table(rigs: Iterable[RigInfo]) -> list[str]:
    """Lines listing `rigs` in columns under a header."""
    rows = [("PORT", "HARDWARE ID", "LABEL", "FIRMWARE")] + [
        (rig.port, rig.hardware_id, "in use", "")
        if rig.label is None
        else (rig.port, rig.hardware_id, rig.label, rig.firmware_version or "")
        for rig in rigs
    ]
    widths = [max(len(row[column]) for row in rows) for column in range(3)]
    return ["  ".join([*map(str.ljust, row[:3], widths), row[3]]).rstrip() for row in rows]


def _find(cls: type[_Rig], name: str | None, log_level: int | None) -> _Rig:
    """Opens the USB Rig `name` picks: by port, then Hardware ID, then label."""
    ports = usb_ports()
    if name is None:
        if len(ports) == 1:
            return _open(cls, ports[0], log_level)
        if not ports:
            raise RigNotFoundError(
                "No Rig is plugged in. To use the simulator, pass its tcp://host:port address."
            )
        raise AmbiguousRigError(
            _with_table(
                f"{len(ports)} Rigs are plugged in; pass Rig.connect() the label, Hardware ID "
                "or port of one:",
                [_info(cls, port) for port in ports],
            )
        )
    for port in ports:
        if _same_port(port.device, name):
            return _open(cls, port, log_level)
    for port in ports:
        if port.hardware_id.casefold() == name.casefold():
            rig = _open(cls, port, log_level)
            if rig.hardware_id != port.hardware_id:
                rig.close()
                raise ItchError(
                    f"The Rig on {port.device} says its Hardware ID is {rig.hardware_id}, "
                    f"but its USB port says {port.hardware_id}; tell the dev."
                )
            return rig
    return _find_label(cls, ports, name, log_level)


def _find_label(cls: type[_Rig], ports: list[UsbPort], label: str, log_level: int | None) -> _Rig:
    """Opens every free Rig to find the one labelled `label`, and closes the rest."""
    found: list[RigInfo] = []
    matches: list[_Rig] = []
    try:
        for port in ports:
            rig, info = _probe(cls, port)
            found.append(info)
            if rig is None:
                continue
            if _same_label(info, label):
                matches.append(rig)
            else:
                rig.close()
        if len(matches) == 1:
            (rig,) = matches
            if log_level is not None:
                rig._set_log_level(log_level)  # pyright: ignore[reportPrivateUsage]
            return rig
    except BaseException:
        for rig in matches:
            rig.close()
        raise
    for rig in matches:
        rig.close()
    if matches:
        raise AmbiguousRigError(
            _with_table(
                f"{len(matches)} Rigs are labelled {label!r}; pass Rig.connect() the Hardware ID "
                "or port of one:",
                [info for info in found if _same_label(info, label)],
            )
        )
    if not found:
        raise RigNotFoundError(f"Rig {label!r} not found: no Rig is plugged in.")
    busy = [info.port for info in found if info.in_use]
    in_use = (
        f"; {len(busy)} {'Rig is' if len(busy) == 1 else 'Rigs are'} in use by another "
        f"program: {', '.join(busy)}"
        if busy
        else ""
    )
    raise RigNotFoundError(_with_table(f"Rig {label!r} not found{in_use}. Rigs found:", found))


def _open(cls: type[_Rig], port: UsbPort, log_level: int | None) -> _Rig:
    try:
        return cls(UsbTransport(port.device), log_level=log_level)
    except PortInUse:
        raise RigNotFoundError(
            f"Rig {port.hardware_id} on {port.device} is in use by another program."
        ) from None


def _probe(cls: type[_Rig], port: UsbPort) -> tuple[_Rig | None, RigInfo]:
    """Opens a Rig to ask who it is, leaving it open. `None` if another program has it."""
    try:
        rig = cls(UsbTransport(port.device))
    except PortInUse:
        return None, RigInfo(port.device, port.hardware_id, None, None)
    return rig, RigInfo(port.device, rig.hardware_id, rig.label, rig.firmware_version)


def _info(cls: type[_Rig], port: UsbPort) -> RigInfo:
    rig, info = _probe(cls, port)
    if rig is not None:
        rig.close()
    return info


def _same_port(device: str, name: str) -> bool:
    if sys.platform == "win32":
        return device.casefold() == name.casefold()
    return os.path.realpath(device) == os.path.realpath(name)  # Such as /dev/serial/by-id/…


def _same_label(info: RigInfo, label: str) -> bool:
    return info.label is not None and info.label.casefold() == label.casefold()


def _with_table(message: str, rigs: list[RigInfo]) -> str:
    return "\n  ".join([message, *rig_table(rigs)])


def _new_token() -> int:
    """A random non-zero Lease token."""
    while not (token := secrets.randbits(64)):
        pass
    return token


def _default_holder() -> str:
    """`user@host script.py`, each part cut short with `…` so the whole fits 64 bytes."""
    user = _fit(getpass.getuser(), 16)
    host = _fit(socket.gethostname(), 24)
    script = Path(sys.argv[0]).name if sys.argv else ""
    start = f"{user}@{host} "
    return start + _fit(script or "python", _wire.MAX_LABEL - len(start.encode()))


def _fit(text: str, size: int) -> str:
    """`text`, cut short with `…` on a character boundary to fit `size` bytes of UTF-8."""
    data = text.encode()
    if len(data) <= size:
        return text
    return data[: size - len("…".encode())].decode(errors="ignore") + "…"


def _bit(channel: int) -> int:
    # `in range` alone would let `True` through as CH1 and `1.0` through as a float.
    if type(channel) is not int or channel not in CHANNELS:
        raise ValueError(f"Channel {channel!r} doesn't exist: a Rig's Channels are 1 to 16.")
    return 1 << (channel - 1)


def _is_on(position: Position) -> bool:
    if position not in ("on", "off"):
        raise ValueError(f'{position!r} isn\'t a Channel position: use "on" or "off".')
    return position == "on"
