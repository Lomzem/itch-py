from __future__ import annotations

import getpass
import logging
import socket
import warnings
from collections.abc import Callable, Iterable, Mapping
from types import TracebackType
from typing import Literal, Self

from itch import _wire
from itch._connection import Connection
from itch._discovery import RigInfo, find_rig, rig_infos
from itch._errors import DevelopmentBuildWarning, DisconnectedError, ItchError, LockedError
from itch._status import Status, from_reply
from itch._transport import open_tcp

CHANNELS = range(1, 17)
"""The Channel numbers, CH1 to CH16 as on the board."""

Position = Literal["on", "off"]
"""A Channel's state. "on" means the contact is closed, like a DIP switch's ON."""

_LOGGER = logging.getLogger("itch")


class Rig:
    """A connected Rig. Get one with `Rig.connect()`, and close it when done.

    ```python
    with Rig.connect("bench3") as rig:
        print(rig.label, rig.hardware_id, rig.firmware_version)
        rig.set_channel(3, "on")
    ```
    """

    def __init__(self, connection: Connection, holder: str) -> None:
        """Takes over an open connection. Use `Rig.connect()` instead."""
        self._connection = connection
        self._holder = holder
        """Sent with every change, so a Rig Locked under this name accepts it."""
        self._label = connection.hello.label
        self._locked = False
        """Whether this Rig Locked the Rig and hasn't released it since."""

    @classmethod
    def connect(
        cls,
        name: str | None = None,
        *,
        holder: str | None = None,
        lock: bool = True,
        take_over: bool = False,
        log_level: int | None = None,
    ) -> Self:
        """Connects to a Rig and checks it speaks this itch-py's protocol.

        `name` picks a Rig plugged in over USB by its port (`COM4`, `/dev/ttyACM0`), its
        Hardware ID (`60:55:F9:C0:27:18`) or its label (`bench3`), ignoring case. Leave it out
        when only one Rig is plugged in. A label lookup skips Rigs other programs have open.
        `tcp://host:port` reaches `itch-sim` or a Rig on the network.

        `holder` names this script to colleagues in every change it makes, 1 to 64 bytes of
        UTF-8. It defaults to `user@host`, cut short to 64 bytes. Two scripts run by the same
        user on the same computer share it, and so share the Lock.

        Connecting Locks the Rig under `holder` until `close()`, so nobody else's script can
        change it, as `rig.lock()` does. Pass `lock=False` to only look at a Rig someone else
        has Locked: changes then succeed only while the Rig is unlocked. Pass `take_over=True`
        to take the Lock from whoever holds it; their next change then raises `LockedError`.

        Raises `RigNotFoundError` or `AmbiguousRigError`, listing the Rigs found, if `name`
        doesn't pick out one Rig, and `ItchError` if the USB Rig that answers has another
        Hardware ID than its port lists, or if `holder` is left out and the user or host name
        can't be read. Raises `LockedError` if another Holder has Locked the Rig. Raises
        `ValueError` if `holder` is empty or over 64 bytes. Warns with
        `DevelopmentBuildWarning` if the Rig runs a development build.

        The Rig's own log messages are off unless you pass `log_level`, such as
        `logging.INFO`. Those at that level and above then go to the `itch.rig` logger
        whenever itch-py hears from the Rig, and when it closes. Configure Python `logging`
        to see them.
        """
        holder = _default_holder() if holder is None else _checked_holder(holder)
        if name is not None and name.startswith("tcp://"):
            rig = cls(Connection.open(open_tcp(name), log_level=log_level), holder)
        else:
            rig = cls(find_rig(name, log_level), holder)
        try:
            if lock:
                rig.lock(take_over=take_over)
            if rig._connection.hello.dirty:
                warnings.warn(
                    f"Rig {rig.label} runs a development build, built from uncommitted code. "
                    "Have the dev flash a release build before QA use it.",
                    DevelopmentBuildWarning,
                    stacklevel=2,
                )
        except BaseException:
            rig.close()  # Locking failed, or the warning was turned into an error.
            raise
        return rig

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
        and call `.release()`. `close()` releases it too. Locking again under the same Holder,
        as after a crash or a dropped connection, picks the Lock back up.

        The Rig holds one Lock per Holder and doesn't count them: releasing any `RigLock`
        unlocks the Rig, including the Lock `Rig.connect()` took.

        Raises `LockedError` if another Holder has Locked the Rig, unless `take_over` is true:
        that takes the Lock from them, and their next change raises `LockedError`.
        """
        self._connection.request(_wire.Lock(self._holder, take_over), _wire.LockReply)
        self._locked = True
        return RigLock(self._release_lock)

    def set_channel(self, ch: int, pos: Position) -> None:
        """Turns Channel `ch` on or off."""
        self.set_channels({ch: pos})

    def set_channels(self, positions: Mapping[int, Position]) -> None:
        """Turns the listed Channels on or off together, in one write, leaving the rest alone.

        `positions` is `{ch: pos}`.
        """
        mask = values = 0
        for channel, position in positions.items():
            bit = _bit(channel)
            mask |= bit
            if _is_on(position):
                values |= bit
        self._write_channels(mask, values)

    def clear(self) -> None:
        """Turns every Channel off."""
        self._connection.request(_wire.Clear(self._holder), _wire.ClearReply)

    def get_channel(self, ch: int) -> Position:
        """Returns whether the Rig commands Channel `ch` "on" or "off"."""
        return self.get_channels([ch])[ch]

    def get_channels(self, chs: Iterable[int] | None = None) -> dict[int, Position]:
        """Returns `{ch: "on" | "off"}` for the Channels in `chs`, or all 16."""
        wanted = {ch: _bit(ch) for ch in (CHANNELS if chs is None else chs)}
        state = self._read_channels()
        return {ch: "on" if state & bit else "off" for ch, bit in wanted.items()}

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

    def status(self) -> Status:
        """Returns the Rig's health since boot, who holds its Lock, and its network."""
        return from_reply(self._connection.request(_wire.GetStatus(), _wire.GetStatusReply))

    def close(self) -> None:
        """Releases this script's Lock, if it holds one, and closes the connection.

        Safe to call twice. The Channels stay as they are: the Rig keeps them for the next
        script. If someone took the Lock over, or releasing fails, `close()` logs a warning to
        the `itch` logger instead of raising.
        """
        try:
            self._release_lock()
        except ItchError as err:
            _LOGGER.warning("Couldn't release Rig %s's Lock: %s", self.label, err)
        finally:
            self._connection.close()

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

    def _write_channels(self, mask: int, values: int) -> None:
        """One Mask write: the Channels in `mask` take their bits from `values`."""
        request = _wire.WriteChannels(self._holder, mask, values)
        self._connection.request(request, _wire.WriteChannelsReply)

    def _read_channels(self) -> int:
        """The commanded state of all 16 Channels, bit 0 for CH1."""
        return self._connection.request(_wire.GetChannels(), _wire.GetChannelsReply).state

    def _release_lock(self) -> None:
        """Releases the Lock if this Rig holds it.

        A Takeover means it is already released, so that only logs a warning. A dropped
        connection can't release it; reconnecting under the same Holder picks it back up.
        """
        if not self._locked:
            return
        self._locked = False
        try:
            self._connection.request(_wire.ReleaseLock(self._holder), _wire.ReleaseLockReply)
        except LockedError:
            _LOGGER.warning(
                "Rig %s was taken over before %s released its Lock.", self.label, self._holder
            )
        except DisconnectedError:
            pass


class RigLock:
    """A Lock this script holds on a Rig. Get one from `rig.lock()`.

    ```python
    with rig.lock():
        rig.set_channel(3, "on")
    ```

    Leaving the block, or calling `.release()`, releases the Lock.
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


def list_rigs() -> list[RigInfo]:
    """The Rigs plugged in over USB.

    Opens each free Rig briefly to ask its label and firmware version. Rigs other programs
    have open are listed as in use, without disturbing them. A free Rig that fails to answer
    is listed with its `error`.
    """
    return rig_infos()


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


def _bit(channel: int) -> int:
    # `in range` alone would let `True` through as CH1 and `1.0` through as a float.
    if type(channel) is not int or channel not in CHANNELS:
        raise ValueError(f"Channel {channel!r} doesn't exist: a Rig's Channels are 1 to 16.")
    return 1 << (channel - 1)


def _is_on(position: Position) -> bool:
    if position not in ("on", "off"):
        raise ValueError(f'{position!r} isn\'t a Channel position: use "on" or "off".')
    return position == "on"
