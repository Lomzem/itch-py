from __future__ import annotations

import contextlib
import functools
import warnings
from collections.abc import Callable, Iterable, Mapping
from types import TracebackType
from typing import Literal, Self

from itch import _wire
from itch._connection import Connection
from itch._discovery import RigInfo, find_rig, rig_infos
from itch._errors import DevelopmentBuildWarning, ItchError, LeaseRequiredError
from itch._lease import Lease
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
        with rig.session():
            rig.set_channel(3, "on")
    ```
    """

    def __init__(self, connection: Connection) -> None:
        """Takes over an open connection. Use `Rig.connect()` instead."""
        self._connection = connection
        self._label = connection.hello.label
        self._lease: Lease | None = None
        """The current session's Lease."""

    @classmethod
    def connect(cls, name: str | None = None, *, log_level: int | None = None) -> Self:
        """Connects to a Rig and checks it speaks this itch-py's protocol.

        `name` picks a Rig plugged in over USB by its port (`COM4`, `/dev/ttyACM0`), its
        Hardware ID (`60:55:F9:C0:27:18`) or its label (`bench3`), ignoring case. Leave it out
        when only one Rig is plugged in. A label lookup skips Rigs other programs have open.
        `tcp://host:port` reaches `itch-sim` or a dev-build Rig.

        Raises `RigNotFoundError` or `AmbiguousRigError`, listing the Rigs found, if `name`
        doesn't pick out one Rig, and `ItchError` if the USB Rig that answers has another
        Hardware ID than its port lists. Warns with `DevelopmentBuildWarning` if the Rig runs a
        development build.

        The Rig's own log messages are off unless you pass `log_level`, such as
        `logging.INFO`. Those at that level and above then go to the `itch.rig` logger
        whenever itch-py hears from the Rig, and when it closes. Configure Python `logging`
        to see them.
        """
        if name is not None and name.startswith("tcp://"):
            rig = cls(Connection.open(open_tcp(name), log_level=log_level))
        else:
            rig = cls(find_rig(name, log_level))
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
        return self._connection.hardware_id

    @property
    def firmware_version(self) -> str:
        """The Rig's firmware version, such as `1.0.0`."""
        return self._connection.hello.firmware_version

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
                f"Rig {self._label} already has a session: release it before starting another."
            )
        lease = Lease.acquire(self._connection, holder, takeover=takeover)
        self._lease = lease
        return Session(functools.partial(self._release, lease))

    def set_channel(self, ch: int, pos: Position) -> None:
        """Turns Channel `ch` on or off. Needs a session."""
        self.set_channels({ch: pos})

    def set_channels(self, positions: Mapping[int, Position]) -> None:
        """Turns the listed Channels on or off together, in one write, leaving the rest alone.

        `positions` is `{ch: pos}`. Needs a session.
        """
        mask = values = 0
        for channel, position in positions.items():
            bit = _bit(channel)
            mask |= bit
            if _is_on(position):
                values |= bit
        self._write_channels(mask, values)

    def clear(self) -> None:
        """Turns every Channel off. Needs a session."""
        self._connection.request(_wire.Clear(self._token()), _wire.ClearReply)

    def get_channel(self, ch: int) -> Position:
        """Returns whether the Rig commands Channel `ch` "on" or "off"."""
        return self.get_channels([ch])[ch]

    def get_channels(self, chs: Iterable[int] | None = None) -> dict[int, Position]:
        """Returns `{ch: "on" | "off"}` for the Channels in `chs`, or all 16."""
        wanted = {ch: _bit(ch) for ch in (CHANNELS if chs is None else chs)}
        state = self._read_channels()
        return {ch: "on" if state & bit else "off" for ch, bit in wanted.items()}

    def set_label(self, label: str) -> None:
        """Renames the Rig, at most 64 bytes of UTF-8. Needs a session.

        The Rig keeps the label across reboots. An empty label restores the default, such as
        `itch-C02718`. Raises `StorageFaultError` if the Rig couldn't save it.
        """
        if (size := len(label.encode())) > _wire.MAX_LABEL:
            raise ValueError(
                f"The label {label!r} is {size} bytes, but at most {_wire.MAX_LABEL} bytes fit."
            )
        request = _wire.SetLabel(self._token(), label)
        reply = self._connection.request(request, _wire.SetLabelReply)
        self._label = self._connection.name = reply.label

    def status(self) -> Status:
        """Returns the Rig's uptime, reset reason, last panic, Holder and fault counters."""
        return from_reply(self._connection.request(_wire.GetStatus(), _wire.GetStatusReply))

    def close(self) -> None:
        """Closes the connection, freeing the Rig for the next script. Safe to call twice.

        Releases the session first, if there is one.
        """
        if self._lease is not None:
            with contextlib.suppress(ItchError):
                self._release(self._lease)
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

    @property
    def _dev_build_notes(self) -> list[str]:
        hello = self._connection.hello
        notes: list[str] = []
        if hello.features & _wire.FEATURE_WIFI:
            notes.append("WiFi enabled")
        if hello.dirty:
            notes.append("built from uncommitted code")
        return notes

    def _write_channels(self, mask: int, values: int) -> None:
        """One Mask write: the Channels in `mask` take their bits from `values`."""
        request = _wire.WriteChannels(self._token(), mask, values)
        self._connection.request(request, _wire.WriteChannelsReply)

    def _read_channels(self) -> int:
        """The commanded state of all 16 Channels, bit 0 for CH1."""
        return self._connection.request(_wire.GetChannels(), _wire.GetChannelsReply).state

    def _token(self) -> int:
        """The Lease token for a write.

        Raises `LeaseRequiredError` outside a session, and `LeaseLostError` once the heartbeat
        has seen someone else take the Rig.
        """
        if self._lease is None:
            raise LeaseRequiredError
        return self._lease.token()

    def _release(self, lease: Lease) -> None:
        if self._lease is lease:
            self._lease = None
        lease.release()


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


def list_rigs() -> list[RigInfo]:
    """The Rigs plugged in over USB.

    Opens each free Rig briefly to ask its label and firmware version. Rigs other programs
    have open are listed as in use, without disturbing them. A free Rig that fails to answer
    is listed with its `error`.
    """
    return rig_infos()


def _bit(channel: int) -> int:
    # `in range` alone would let `True` through as CH1 and `1.0` through as a float.
    if type(channel) is not int or channel not in CHANNELS:
        raise ValueError(f"Channel {channel!r} doesn't exist: a Rig's Channels are 1 to 16.")
    return 1 << (channel - 1)


def _is_on(position: Position) -> bool:
    if position not in ("on", "off"):
        raise ValueError(f'{position!r} isn\'t a Channel position: use "on" or "off".')
    return position == "on"
