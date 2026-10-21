from __future__ import annotations

import getpass
import socket
import warnings
from collections.abc import Iterable, Mapping
from types import TracebackType
from typing import Literal, Self

from itch import _wire
from itch._connection import Connection
from itch._discovery import RigInfo, find_rig, rig_infos
from itch._errors import DevelopmentBuildWarning, ItchError
from itch._status import Status, from_reply
from itch._transport import open_tcp

CHANNELS = range(1, 17)
"""The Channel numbers, CH1 to CH16 as on the board."""

Position = Literal["on", "off"]
"""A Channel's state. "on" means the contact is closed, like a DIP switch's ON."""


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

    @classmethod
    def connect(
        cls, name: str | None = None, *, holder: str | None = None, log_level: int | None = None
    ) -> Self:
        """Connects to a Rig and checks it speaks this itch-py's protocol.

        `name` picks a Rig plugged in over USB by its port (`COM4`, `/dev/ttyACM0`), its
        Hardware ID (`60:55:F9:C0:27:18`) or its label (`bench3`), ignoring case. Leave it out
        when only one Rig is plugged in. A label lookup skips Rigs other programs have open.
        `tcp://host:port` reaches `itch-sim` or a Rig on the network.

        `holder` names this script to colleagues in every change it makes, 1 to 64 bytes of
        UTF-8. It defaults to `user@host`, cut short to 64 bytes. Two scripts run by the same
        user on the same computer share it.

        Raises `RigNotFoundError` or `AmbiguousRigError`, listing the Rigs found, if `name`
        doesn't pick out one Rig, and `ItchError` if the USB Rig that answers has another
        Hardware ID than its port lists, or if `holder` is left out and the user or host name
        can't be read. Raises `ValueError` if `holder` is empty or over 64 bytes. Warns with
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
        if rig._connection.hello.dirty:
            try:
                warnings.warn(
                    f"Rig {rig.label} runs a development build, built from uncommitted code. "
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
        return self._connection.hardware_id

    @property
    def firmware_version(self) -> str:
        """The Rig's firmware version, such as `1.0.0`."""
        return self._connection.hello.firmware_version

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
        """Closes the connection. Safe to call twice.

        The Channels stay as they are: the Rig keeps them for the next script.
        """
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
