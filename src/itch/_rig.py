from __future__ import annotations

import functools
import getpass
import logging
import socket
import threading
import warnings
from collections.abc import Callable, Iterable, Mapping
from ipaddress import IPv4Address, IPv4Interface
from types import TracebackType
from typing import TYPE_CHECKING, Literal, NoReturn, Self, TypeVar, overload

from itch import _mdns, _wire
from itch._connection import Connection
from itch._discovery import RigInfo, find_rig, rig_infos
from itch._endpoints import claim, forget
from itch._errors import DevelopmentBuildWarning, DisconnectedError, ItchError, LockedError
from itch._status import Status, from_reply
from itch._transport import open_tcp

if TYPE_CHECKING:
    from itch._profile import Profile

CHANNELS = range(1, 17)
"""The Channel numbers, CH1 to CH16 as on the board."""

Position = Literal["on", "off"]
"""A Channel's state. "on" means the contact is closed, like a DIP switch's ON."""

ALL_CHANNELS = 0xFFFF
"""The mask of all 16 Channels."""

P = TypeVar("P", bound="Profile")

_LOGGER = logging.getLogger("itch")

_NOT_UNICAST = "it must not be zero, 255.255.255.255 or multicast."

REMOVED = {
    "set_channel": "Use set(...) to turn Channels on, clear(...) to turn them off, or "
    "write(set=[...], clear=[...]) for both in one write.",
    "set_channels": "Use set(...) to turn Channels on, clear(...) to turn them off, or "
    "write(set=[...], clear=[...]) for both in one write.",
    "get_channel": "Use get(channel), which returns True when the Channel is on.",
    "get_channels": "Use get_all() to read all 16 Channels, or get(channel) for one.",
    "close": "Use disconnect().",
}
"""Methods removed in itch-py 0.3.0, and what to use instead."""


class Rig:
    """A connected Rig. Get one with `Rig.connect()`, and disconnect it when done.

    ```python
    rig = Rig.connect("bench3")
    rig.set(3)
    rig.disconnect()

    with Rig.connect("bench3") as rig:  # Leaving the block disconnects.
        print(rig.label, rig.hardware_id, rig.firmware_version)
        rig.set(3)
    ```
    """

    def __init__(self, connection: Connection, holder: str) -> None:
        """Takes over an open connection. Use `Rig.connect()` instead."""
        self._connection = connection
        self._holder = holder
        """Sent with every change, so a Rig Locked under this name accepts it."""
        self._label = connection.hello.label
        self._locks = _Locks(connection, holder)
        # Disconnects an older Rig this process has there. Disconnecting this one needs only its
        # Locks and connection, so it still happens at exit if the script drops this Rig.
        claim(connection.endpoint, self, functools.partial(_disconnect, self._locks, connection))

    @overload
    @classmethod
    def connect(
        cls,
        name: str | None = None,
        profile: None = None,
        *,
        holder: str | None = None,
        lock: bool = True,
        take_over: bool = False,
        log_level: int | None = None,
        browse_timeout: float = _mdns.BROWSE_TIMEOUT,
    ) -> Self: ...
    @overload
    @classmethod
    def connect(
        cls,
        name: str | None,
        profile: type[P],
        *,
        holder: str | None = None,
        lock: bool = True,
        take_over: bool = False,
        log_level: int | None = None,
        browse_timeout: float = _mdns.BROWSE_TIMEOUT,
    ) -> P: ...
    @overload
    @classmethod
    def connect(
        cls,
        name: str | None = None,
        *,
        profile: type[P],
        holder: str | None = None,
        lock: bool = True,
        take_over: bool = False,
        log_level: int | None = None,
        browse_timeout: float = _mdns.BROWSE_TIMEOUT,
    ) -> P: ...
    @classmethod
    def connect(
        cls,
        name: str | None = None,
        profile: type[Profile] | None = None,
        *,
        holder: str | None = None,
        lock: bool = True,
        take_over: bool = False,
        log_level: int | None = None,
        browse_timeout: float = _mdns.BROWSE_TIMEOUT,
    ) -> Self | Profile:
        """Connects to a Rig and checks it speaks this itch-py's protocol.

        Returns the `Rig`, or with a `profile`, such as `Rig.connect("bench3", AcmeWidget)`,
        a DUT of that Profile: one object driving the Profile's Fields and the Rig's Channels,
        with the Rig itself as `dut.rig`. `Rig.connect(profile=AcmeWidget)` connects to the one
        Rig plugged in. Every other option works the same with or without a Profile.

        `name` picks a Rig plugged in over USB by its port (`COM4`, `/dev/ttyACM0`), its
        Hardware ID (`60:55:F9:C0:27:18`) or its label (`bench3`), ignoring case. Leave it out
        when only one Rig is plugged in. A label lookup skips Rigs other programs have open.
        If no USB Rig has the Hardware ID or label, itch-py browses the network over mDNS for
        `browse_timeout` seconds, 3 by default, and connects to the Rig advertising it.
        `tcp://host:port` reaches `itch-sim` or a Rig on the network without browsing.

        Connecting to a USB port or network address this script has already connected to, as
        when a notebook cell runs again, first disconnects the older connection, releasing its
        Lock. Using the older `Rig`, or a DUT on it, then raises `DisconnectedError`.

        `holder` names this script to colleagues in every change it makes, 1 to 64 bytes of
        UTF-8. It defaults to `user@host`, cut short to 64 bytes. Two scripts run by the same
        user on the same computer share it, and so share the Lock.

        Connecting Locks the Rig under `holder` until `disconnect()`, or until this script ends
        normally or on an uncaught exception, so nobody else's script can change it, as
        `rig.lock()` does. A killed script leaves its Lock, which `holder` picks back up on
        connecting again. Pass `lock=False` to only look at a Rig someone else
        has Locked: changes then succeed only while the Rig is unlocked. Pass `take_over=True`
        to take the Lock from whoever holds it; their next change then raises `LockedError`.

        Raises `RigNotFoundError` or `AmbiguousRigError`, listing the Rigs found, if `name`
        doesn't pick out one Rig, and `ItchError` if the Rig that answers has another
        Hardware ID than its USB port lists or it advertises, if a Rig on the network refuses
        the connection, or if `holder` is left out and the user or host name can't be read.
        Raises `LockedError` if another Holder has Locked the Rig. Raises `ValueError` if
        `holder` is empty or over 64 bytes, and `TypeError` if `profile` isn't a Profile
        subclass, both before connecting. Warns with
        `DevelopmentBuildWarning` if the Rig runs a development build.

        The Rig's own log messages are off unless you pass `log_level`, such as
        `logging.INFO`. Those at that level and above then go to the `itch.rig` logger
        whenever itch-py hears from the Rig, and when it closes. Configure Python `logging`
        to see them.
        """
        from itch._profile import check_profile, connected  # It imports this module.

        if profile is not None:
            check_profile(profile)
        holder = _default_holder() if holder is None else _checked_holder(holder)
        if name is not None and name.startswith("tcp://"):
            rig = cls(Connection.open(open_tcp(name), log_level=log_level), holder)
        else:
            rig = cls(find_rig(name, log_level, browse_timeout), holder)
        try:
            if lock:
                rig.lock(take_over=take_over)  # A RigLock that only `disconnect()` releases.
            if rig._connection.hello.dirty:
                warnings.warn(
                    f"Rig {rig.label} runs a development build, built from uncommitted code. "
                    "Have the dev flash a release build before QA use it.",
                    DevelopmentBuildWarning,
                    stacklevel=2,
                )
        except BaseException:
            rig.disconnect()  # Locking failed, or the warning was turned into an error.
            raise
        return rig if profile is None else connected(profile, rig)

    @property
    def label(self) -> str:
        """The Rig's Label, such as `itch-C02718`."""
        return self._label

    @property
    def hardware_id(self) -> str:
        """The Rig's Hardware ID, such as `60:55:F9:C0:27:18`."""
        return self._connection.hardware_id

    @property
    def firmware_version(self) -> str:
        """The Rig's firmware version, such as `1.0.0`."""
        return self._connection.hello.firmware_version

    @property
    def holder(self) -> str:
        """The Holder this script Locks under and sends with every change, such as `qa@bench-pc`."""
        return self._holder

    def lock(self, take_over: bool = False) -> RigLock:
        """Locks the Rig under this script's Holder now, so nobody else's script can change it.

        Use it as `with rig.lock(): ...` to release the Lock when the block ends, or keep it
        and call `.release()`. `disconnect()` releases it too. Locking again under the same
        Holder, as after a crash or a dropped connection, picks the Lock back up.

        Locks nest: the Rig stays Locked until every `RigLock` is released, including the
        Lock `Rig.connect()` took, so `with rig.lock():` inside a Locked script leaves it
        Locked.

        Raises `LockedError` if another Holder has Locked the Rig, unless `take_over` is true:
        that takes the Lock from them, and their next change raises `LockedError`.
        """
        self._locks.take(take_over)
        return RigLock(self._locks.release_one)

    def set(self, *channels: int) -> None:
        """Turns `channels` on, in one write, leaving the rest as they are: `rig.set(1, 5)`.

        Raises `ValueError`, sending nothing, if no Channels are given or one isn't 1 to 16.
        """
        if not channels:
            raise ValueError("No Channels given: name the Channels to turn on, as in set(1, 5).")
        bits = ch(*channels)
        self._write_channels(bits, bits)

    def clear(self, *channels: int) -> None:
        """Turns `channels` off, in one write, leaving the rest as they are: `rig.clear(3)`.

        Raises `ValueError`, sending nothing, if no Channels are given, so a computed empty
        selection never turns every Channel off; `clear_all()` does that. Also raises it if a
        Channel isn't 1 to 16.
        """
        if not channels:
            raise ValueError("No Channels given; use clear_all() to turn every Channel off.")
        self._write_channels(ch(*channels), 0)

    def write(self, *, set: Iterable[int] = (), clear: Iterable[int] = ()) -> None:
        """Turns the Channels in `set` on and those in `clear` off, in one write, leaving the
        rest as they are: `rig.write(set=[1, 5], clear=[3])`.

        Raises `ValueError`, sending nothing, if both are empty, a Channel is in both, or a
        Channel isn't 1 to 16.
        """
        on, off = ch(*set), ch(*clear)
        if both := on & off:
            raise ValueError(
                f"{_channels_named(both)} can't be in both set and clear; pick one for each."
            )
        if not on | off:
            raise ValueError(
                "No Channels given; use clear_all() for a full Clear, or name Channels to set "
                "or clear."
            )
        self._write_channels(on | off, on)

    def apply(self, state: int, *, mask: int = ALL_CHANNELS) -> None:
        """Writes the 16-bit `state` to the Channels in `mask`, in one write, leaving the rest
        as they are. Bit 0 is CH1 and bit 15 is CH16, so `ch()` builds both from Channel
        numbers.

        `rig.apply(0x6742)` writes every Channel. `rig.apply(0x6742, mask=0xFF00)` writes
        CH9 to CH16 only, ignoring the bits of `state` outside `mask`. A `ChannelState` from
        `get_all()` can be applied back.

        Raises `ValueError`, sending nothing, if `state` or `mask` isn't an `int` from 0 to
        0xFFFF, or `mask` is 0.
        """
        _checked_word(state, "state")
        if _checked_word(mask, "mask") == 0:
            raise ValueError("The mask 0 selects no Channels: name some, as in mask=ch(1, 5).")
        self._write_channels(mask, state & mask)

    def set_all(self) -> None:
        """Turns every Channel on, in one write."""
        self.apply(ALL_CHANNELS)

    def clear_all(self) -> None:
        """Turns every Channel off: the Clear."""
        self._connection.request(_wire.Clear(self._holder), _wire.ClearReply)

    def get(self, channel: int) -> bool:
        """Whether the Rig commands Channel `channel` on, read from the Rig now."""
        bit = _bit(channel)
        return bool(self._read_channels() & bit)

    def get_all(self) -> ChannelState:
        """The state of all 16 Channels, read from the Rig now in one request."""
        return ChannelState(self._read_channels())

    def set_label(self, label: str) -> None:
        """Renames the Rig, at most 64 bytes of UTF-8.

        The Rig keeps the label across reboots. An empty label restores the default, such as
        `itch-C02718`. Raises `StorageFaultError` if the Rig couldn't save it.
        """
        if (size := len(label.encode())) > _wire.MAX_LABEL:
            raise ValueError(
                f"The label {label!r} is {size} bytes, but at most {_wire.MAX_LABEL} bytes fit."
            )
        request = _wire.SetLabel(self._holder, label)
        reply = self._connection.request(request, _wire.SetLabelReply)
        self._label = self._connection.name = reply.label

    def set_wifi(self, ssid: str, passphrase: str) -> None:
        """Gives the Rig credentials for the Wi-Fi network `ssid`, replacing any it had.

        `ssid` is 1 to 32 bytes of UTF-8 and `passphrase` 8 to 63; if not, `ValueError` says
        which is wrong and nothing is sent. The Rig keeps the credentials across reboots and
        never reports the passphrase. It then leaves Wi-Fi and joins `ssid`.

        Connected over the network, the Rig may drop the connection as it rejoins. This still
        returns, and the next call raises `DisconnectedError`: reconnect after the network
        change. Raises `LockedError` if another Holder has Locked the Rig, and
        `StorageFaultError`, keeping the old credentials, if the Rig couldn't save them.
        """
        if not 1 <= (size := len(ssid.encode())) <= _wire.MAX_SSID:
            raise ValueError(
                f"The SSID {ssid!r} is {size} bytes, but it must be 1 to {_wire.MAX_SSID}."
            )
        if not _wire.MIN_PASSPHRASE <= (size := len(passphrase.encode())) <= _wire.MAX_PASSPHRASE:
            raise ValueError(
                f"The passphrase is {size} bytes, but it must be {_wire.MIN_PASSPHRASE} to "
                f"{_wire.MAX_PASSPHRASE}."
            )
        self._change_network(_wire.SetWifi(self._holder, ssid, passphrase), _wire.SetWifiReply)

    def clear_wifi(self) -> None:
        """Forgets the Rig's Wi-Fi credentials, so it leaves Wi-Fi and works over USB alone.

        Connected over the network, the Rig drops the connection. This still returns, and the
        next call raises `DisconnectedError`. Raises `LockedError` if another Holder has Locked
        the Rig, and `StorageFaultError`, keeping the old credentials, if the Rig couldn't
        forget them.
        """
        self._change_network(_wire.SetWifi(self._holder, "", ""), _wire.SetWifiReply)

    def set_address(self, address: IPv4Interface, gateway: IPv4Address | None = None) -> None:
        """Gives the Rig a static IPv4 address on Wi-Fi instead of taking one from DHCP.

        `address` carries its prefix, such as `IPv4Interface("192.0.2.10/24")`, and `gateway`
        is optional. The Rig applies exactly what it is told, with no conflict check and no
        fallback to DHCP: a wrong static address strands the Rig's Wi-Fi until you fix it over
        USB. The Rig keeps the setting across reboots, and its Wi-Fi credentials.

        Raises `ValueError`, sending nothing, if the address is zero, 255.255.255.255 or
        multicast, the gateway is 255.255.255.255 or multicast, or the prefix is /0. A zero
        gateway means none, as leaving it out does.

        Connected over the network, the Rig moves to the new address about a second after
        replying, which may drop the connection. This still returns, and the next call raises
        `DisconnectedError`: reconnect after the network change. Raises `LockedError` if another
        Holder has Locked the Rig, and `StorageFaultError`, keeping the old setting, if the Rig
        couldn't save it.
        """
        if not _wire.is_unicast(address.ip.packed):
            raise ValueError(f"{address.ip} can't be the Rig's address: {_NOT_UNICAST}")
        if address.network.prefixlen == 0:
            raise ValueError("The prefix /0 is too short: it must be 1 to 32, such as /24.")
        packed_gateway = bytes(4) if gateway is None else gateway.packed  # Zero is no gateway.
        if any(packed_gateway) and not _wire.is_unicast(packed_gateway):
            raise ValueError(f"{gateway} can't be the gateway: {_NOT_UNICAST}")
        request = _wire.SetAddress(
            self._holder,
            _wire.ADDRESS_STATIC,
            address.ip.packed,
            address.network.prefixlen,
            packed_gateway,
        )
        self._change_network(request, _wire.SetAddressReply)

    def use_dhcp(self) -> None:
        """Has the Rig take its IPv4 address on Wi-Fi from DHCP, the default.

        Connected over the network, the Rig may move to a new address, dropping the
        connection. This still returns, and the next call raises `DisconnectedError`: reconnect
        after the network change. Raises `LockedError` if another Holder has Locked the Rig,
        and `StorageFaultError`, keeping the old setting, if the Rig couldn't save it.
        """
        request = _wire.SetAddress(self._holder, _wire.ADDRESS_DHCP, bytes(4), 0, bytes(4))
        self._change_network(request, _wire.SetAddressReply)

    def status(self) -> Status:
        """Returns the Rig's health since boot, who holds its Lock, and its network."""
        return from_reply(self._connection.request(_wire.GetStatus(), _wire.GetStatusReply))

    def disconnect(self) -> None:
        """Releases this script's Lock, if it holds one, and closes the connection, so another
        script can connect. Leaving a `with Rig.connect(...)` block does it too.

        The Channels stay as they are: the Rig keeps them for the next script. Calling it again
        does nothing, and anything else then raises `DisconnectedError`. If someone took the
        Lock over, or releasing fails, it logs a warning to the `itch` logger instead of
        raising. A script that ends without it, normally or on an uncaught exception,
        disconnects as it exits.
        """
        forget(self._connection.endpoint, self)
        _disconnect(self._locks, self._connection)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.disconnect()

    def __repr__(self) -> str:
        return f"<Rig {self.label} {self.hardware_id} firmware {self.firmware_version}>"

    if not TYPE_CHECKING:
        # Hidden from type checkers, so an editor still flags a removed or misspelt method.
        def __getattr__(self, name: str) -> NoReturn:
            raise missing(self, name, REMOVED)

    def _replaced(self) -> None:
        """Disconnects, because this process is connecting to the same Rig again."""
        _disconnect(self._locks, self._connection, replaced=True)

    def _refresh(self) -> None:
        """Asks the Rig its Label again, since another connection may have renamed it.

        Raises `DisconnectedError` if the connection has dropped, after closing it to free the
        port. The Rig stays registered, so connecting there again still says it was replaced.
        """
        try:
            hello = self._connection.request(_wire.Hello(), _wire.HelloReply)
        except DisconnectedError:
            self._connection.close()
            raise
        self._label = self._connection.name = hello.label

    def _write_channels(self, mask: int, values: int) -> None:
        """One Mask write: the Channels in `mask` take their bits from `values`."""
        request = _wire.WriteChannels(self._holder, mask, values)
        self._connection.request(request, _wire.WriteChannelsReply)

    def _change_network(self, body: _wire.RequestBody, reply: type[_wire.ReplyBody]) -> None:
        """Sends a request that changes the Rig's network settings, after which the connection
        may end."""
        self._connection.request(body, reply, changes_network=True)

    def _read_channels(self) -> int:
        """The commanded state of all 16 Channels, bit 0 for CH1."""
        return self._connection.request(_wire.GetChannels(), _wire.GetChannelsReply).state


class _Locks:
    """The Locks a script holds on a Rig over one connection. Kept apart from the `Rig`, so they
    can still be released at exit if the script dropped the Rig."""

    def __init__(self, connection: Connection, holder: str) -> None:
        self._connection = connection
        self._holder = holder
        self._live = 0
        """How many `RigLock`s are live, counting the one `Rig.connect()` took. Releasing the
        last releases the Rig's Lock."""
        self._locking = threading.RLock()
        """Held while `_live` changes and its `Lock` or `ReleaseLock` is exchanged, so a release
        can't unlock the Rig just after another thread Locked it again. Re-entrant, for an
        `itch` log handler that Locks from the warning `_send_release()` logs."""
        self.left_locked = False
        """Set if the connection dropped before `ReleaseLock` could be sent."""

    def take(self, take_over: bool) -> None:
        """Locks the Rig, or picks the Lock up again, for one more `RigLock`."""
        with self._locking:
            self._connection.request(_wire.Lock(self._holder, take_over), _wire.LockReply)
            self._live += 1

    def release_one(self) -> None:
        """Releases one `RigLock`, and the Rig's Lock with the last."""
        with self._locking:
            if self._live == 0:  # `disconnect()` released it already.
                return
            self._live -= 1
            if self._live == 0:
                self._send_release()

    def release_all(self) -> None:
        """Releases the Lock if any `RigLock` is live, making them all released.

        Not held while the connection closes, which waits for the log handlers, since one may be
        waiting to Lock.
        """
        with self._locking:
            if self._live == 0:
                return
            self._live = 0
            self._send_release()

    def _send_release(self) -> None:
        """Sends `ReleaseLock`.

        A Takeover means it is already released, so that only logs a warning. A dropped
        connection can't release it; reconnecting under the same Holder picks it back up.
        """
        try:
            self._connection.request(_wire.ReleaseLock(self._holder), _wire.ReleaseLockReply)
        except LockedError:
            _LOGGER.warning(
                "Rig %s was taken over before %s released its Lock.",
                self._connection.name,
                self._holder,
            )
        except DisconnectedError:
            self.left_locked = True


def _disconnect(locks: _Locks, connection: Connection, *, replaced: bool = False) -> None:
    """Releases the Lock if `locks` hold it, then closes `connection`. Safe to call twice."""
    try:
        locks.release_all()
    except ItchError as err:
        _LOGGER.warning("Couldn't release Rig %s's Lock: %s", connection.name, err)
    finally:
        connection.close(replaced=replaced)


class ChannelState(int):
    """The state of all 16 Channels, as `rig.get_all()` read it: an `int`, bit 0 for CH1.

    ```python
    state = rig.get_all()
    print(state)        # ChannelState(0x6742, on=[2, 7, 9, 10, 11, 14, 15])
    state.get(7)        # True
    rig.apply(state)    # puts every Channel back as it was
    ```

    It is immutable and never asks the Rig again: it keeps the state as read. Arithmetic on it
    gives a plain `int`.
    """

    __slots__ = ()

    def __new__(cls, state: int) -> Self:
        """Raises `ValueError` unless `state` is an `int` from 0 to 0xFFFF."""
        return super().__new__(cls, _checked_word(state, "state"))

    @property
    def on(self) -> frozenset[int]:
        """The Channels that are on."""
        return frozenset(_channels_in(self))

    def get(self, channel: int) -> bool:
        """Whether Channel `channel` is on in this state."""
        return bool(self & _bit(channel))

    def __repr__(self) -> str:
        return f"ChannelState(0x{self:04X}, on={_channels_in(self)})"


class RigLock:
    """A Lock this script holds on a Rig. Get one from `rig.lock()`.

    ```python
    with rig.lock():
        rig.set(3)
    ```

    Leaving the block, or calling `.release()`, releases it. The Rig stays Locked while
    another `RigLock` on it is live, such as the one `Rig.connect()` took.
    """

    def __init__(self, release: Callable[[], None]) -> None:
        """Takes the function that releases the Lock. Use `rig.lock()` instead."""
        self._release: Callable[[], None] | None = release
        """`None` once released."""

    def release(self) -> None:
        """Releases the Lock. Safe to call twice.

        Logs a warning to the `itch` logger instead of raising if someone took it over. Does
        nothing if the connection dropped: the Rig keeps the Lock until the same Holder
        reconnects and releases it.
        """
        if (release := self._release) is not None:
            self._release = None
            release()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def list_rigs(*, browse_timeout: float = _mdns.BROWSE_TIMEOUT) -> list[RigInfo]:
    """The Rigs plugged in over USB, then those on the network.

    Opens each free USB Rig briefly to ask its label and firmware version. Rigs other programs
    have open are listed as in use, without disturbing them. A free Rig that fails to answer
    is listed with its `error`.

    Rigs on the network are those advertised over mDNS within `browse_timeout` seconds, 3 by
    default, listed as they advertise themselves, without connecting to them. A Rig both
    plugged in and on the network is listed once, as plugged in. Listing never Locks a Rig.
    """
    return rig_infos(browse_timeout)


def left_locked(rig: Rig) -> bool:
    """Whether `rig`'s connection dropped before its Lock could be released, so the Rig stays
    Locked by its Holder until that Holder reconnects (ADR 0009). For the CLI, without making
    it part of `Rig`'s public API."""
    return rig._locks.left_locked  # pyright: ignore[reportPrivateUsage]


def _default_holder() -> str:
    """`user@host`, cut short at a character boundary to fit 64 bytes."""
    try:
        user, host = getpass.getuser(), socket.gethostname()
    except (OSError, KeyError, ImportError) as err:  # Such as a container UID with no passwd entry.
        raise ItchError(
            f"Couldn't read this computer's user or host name ({err}); pass "
            'Rig.connect() a holder, such as holder="qa@bench-pc".'
        ) from err
    if not user or not host:
        raise ItchError(
            "Couldn't read this computer's user or host name; pass Rig.connect() a holder, "
            'such as holder="qa@bench-pc".'
        )
    return f"{user}@{host}".encode()[: _wire.MAX_HOLDER].decode(errors="ignore")


def _checked_holder(holder: str) -> str:
    if not 1 <= (size := len(holder.encode())) <= _wire.MAX_HOLDER:
        raise ValueError(
            f"The holder {holder!r} is {size} bytes, but it must be 1 to {_wire.MAX_HOLDER}."
        )
    return holder


def ch(*channels: int) -> int:
    """The bits of `channels`, bit 0 for CH1, to pass `apply()`: `ch(1, 5) == 0x0011`.

    Raises `ValueError` if a Channel isn't 1 to 16.
    """
    bits = 0
    for channel in channels:
        bits |= _bit(channel)
    return bits


def _bit(channel: int) -> int:
    # `in range` alone would let `True` through as CH1 and `1.0` through as a float.
    if type(channel) is not int or channel not in CHANNELS:
        raise ValueError(f"Channel {channel!r} doesn't exist: a Rig's Channels are 1 to 16.")
    return 1 << (channel - 1)


def _channels_in(bits: int) -> list[int]:
    """The Channels whose bits are set, in order."""
    return [channel for channel in CHANNELS if bits & (1 << (channel - 1))]


def _channels_named(bits: int) -> str:
    """`Channel 3`, or `Channels 3, 5` for several."""
    channels = _channels_in(bits)
    return f"Channel{'s' if len(channels) > 1 else ''} {', '.join(map(str, channels))}"


def missing(obj: object, name: str, removed: Mapping[str, str]) -> AttributeError:
    """The error for reading `obj.name`, which doesn't exist, naming its replacement if it was
    one of the `removed` methods."""
    if (instead := removed.get(name)) is None:
        return AttributeError(
            f"{type(obj).__name__!r} object has no attribute {name!r}", name=name, obj=obj
        )
    # `name=None` stops Python adding a "Did you mean" guess, such as set_all for set_channels.
    return AttributeError(
        f"{type(obj).__name__}.{name}() was removed in itch-py 0.3.0. {instead}", name=None
    )


def _checked_word(value: object, name: str) -> int:
    # `bool` is an `int`, but `apply(True)` is surely a mistake.
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ALL_CHANNELS:
        raise ValueError(
            f"{value!r} can't be a Channel {name}: it must be an int from 0 to 0xFFFF, bit 0 "
            "for CH1."
        )
    return value
