"""Finding Rigs plugged in over USB or on the network: picking one by name, and listing them.

A name is looked for over USB first. Only if no USB Rig has it does a lookup browse mDNS.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from typing import Literal

from itch import _mdns, _wire
from itch._connection import Connection, same_hardware_id
from itch._endpoints import held, release, tcp_endpoint, usb_endpoint
from itch._errors import AmbiguousRigError, DisconnectedError, ItchError, RigNotFoundError
from itch._transport import TcpTransport
from itch._usb import PortInUse, UsbPort, UsbTransport, usb_ports


@dataclasses.dataclass(frozen=True)
class RigInfo:
    """A Rig plugged in over USB or advertised on the network, as `list_rigs()` finds it."""

    port: str
    """Where to reach it, for `Rig.connect()`: such as `COM4` or `/dev/ttyACM0` over USB, or
    `tcp://192.0.2.10:7878` on the network."""
    hardware_id: str
    """Such as `60:55:F9:C0:27:18`."""
    label: str | None
    """Such as `bench3`, or `None` if the Rig is in use or failed. On the network, the label
    the Rig advertises, cut to 63 bytes if longer."""
    firmware_version: str | None
    """Such as `1.0.0`, or `None` if the Rig is in use, failed or on the network."""
    error: str | None = None
    """Why itch-py couldn't ask a free Rig its label, such as a protocol mismatch."""
    transport: Literal["usb", "tcp"] = "usb"
    """How it was found: plugged in over USB, or advertised on the network over mDNS."""

    @property
    def in_use(self) -> bool:
        """Whether another program has the USB Rig open, so itch-py couldn't ask its label.

        Always `False` on the network, where listing doesn't connect.
        """
        return self.label is None and self.error is None


def rig_infos(browse_timeout: float) -> list[RigInfo]:
    """The Rigs plugged in over USB, each opened briefly unless in use, then those advertised
    on the network within `browse_timeout` seconds and not plugged in."""
    usb = [_info(port) for port in usb_ports()]
    network = [
        rig
        for rig in _network_infos(_mdns.browse(browse_timeout))
        if not any(same_hardware_id(rig.hardware_id, plugged.hardware_id) for plugged in usb)
    ]
    return usb + sorted(network, key=lambda rig: (str(rig.label).casefold(), rig.hardware_id))


def rig_table(rigs: Iterable[RigInfo]) -> list[str]:
    """Lines listing `rigs` in columns under a header."""
    rows = [("PORT", "HARDWARE ID", "LABEL", "FIRMWARE")] + [_row(rig) for rig in rigs]
    widths = [max(len(row[column]) for row in rows) for column in range(3)]
    return ["  ".join([*map(str.ljust, row[:3], widths), row[3]]).rstrip() for row in rows]


def _row(rig: RigInfo) -> tuple[str, str, str, str]:
    if rig.error is not None:
        return rig.port, rig.hardware_id, "error", rig.error
    if rig.label is None:
        return rig.port, rig.hardware_id, "in use", ""
    return rig.port, rig.hardware_id, rig.label, rig.firmware_version or ""


def find_rig(name: str | None, log_level: int | None, browse_timeout: float) -> Connection:
    """Connects to the Rig `name` picks: over USB by port, Hardware ID or label, then on the
    network by Hardware ID or label, browsing for `browse_timeout` seconds.

    With no `name`, connects to the only Rig plugged in, never one on the network.
    """
    ports = usb_ports()
    if name is None:
        if len(ports) == 1:
            return _open(ports[0], log_level)
        if not ports:
            raise RigNotFoundError(
                "No Rig is plugged in. To use the simulator, pass its tcp://host:port address."
            )
        raise AmbiguousRigError(
            _with_table(
                f"{len(ports)} Rigs are plugged in; pass Rig.connect() the label, Hardware ID "
                "or port of one:",
                [_info(port) for port in ports],
            )
        )
    for port in ports:
        if usb_endpoint(port.device) == usb_endpoint(name):
            return _open(port, log_level)
    for port in ports:
        if same_hardware_id(port.hardware_id, name):
            return _open(port, log_level)
    return _find_named(ports, name, log_level, browse_timeout)


def _find_named(
    ports: list[UsbPort], name: str, log_level: int | None, browse_timeout: float
) -> Connection:
    """Connects to the Rig `name` picks once no USB port or Hardware ID matched it.

    Opens every free USB Rig to find the one labelled `name`, closing the rest, and counts a
    Rig this process has connected if it is labelled `name` now. If none is, browses the
    network for the Rig advertising `name` as its Label or Hardware ID.
    """
    found: list[RigInfo] = []
    matches: list[Connection] = []
    mine: list[UsbPort] = []
    """Ports where this process has connected the Rig labelled `name`, to connect again."""
    try:
        for port in ports:
            if (held_here := held(usb_endpoint(port.device))) is not None and (
                info := _held_info(port, held_here)
            ):
                found.append(info)
                if _same_label(info, name):
                    mine.append(port)
                continue
            connection, info = _probe(port)
            found.append(info)
            if connection is None:
                continue
            if _same_label(info, name):
                matches.append(connection)
            else:
                connection.close()
        if len(matches) + len(mine) == 1:
            if mine:
                return _open(mine[0], log_level)
            (connection,) = matches
            if log_level is not None:
                connection.set_log_level(log_level)
            return connection
    except BaseException:
        for connection in matches:
            connection.close()
        raise
    for connection in matches:
        connection.close()
    if matches or mine:
        raise AmbiguousRigError(
            _with_table(
                f"{len(matches) + len(mine)} Rigs are labelled {name!r}; pass Rig.connect() the "
                "Hardware ID or port of one:",
                [info for info in found if _same_label(info, name)],
            )
        )
    adverts = _mdns.browse(browse_timeout)
    if connection := _find_advert(adverts, name, log_level):
        return connection
    found += _network_infos(adverts)
    if not found:
        raise RigNotFoundError(
            f"Rig {name!r} not found: no Rig is plugged in, and none answered on the network "
            f"within {browse_timeout:g} s."
        )
    busy = [info.port for info in found if info.in_use]
    in_use = (
        f"; {len(busy)} {'Rig is' if len(busy) == 1 else 'Rigs are'} in use by another "
        f"program: {', '.join(busy)}"
        if busy
        else ""
    )
    raise RigNotFoundError(
        _with_table(
            f"Rig {name!r} not found over USB or on the network{in_use}. Rigs found:", found
        )
    )


def _find_advert(
    adverts: list[_mdns.Advert], name: str, log_level: int | None
) -> Connection | None:
    """Connects to the one Rig advertising Hardware ID or label `name`, or `None` if none does."""
    by_label = [advert for advert in adverts if _advertises_label(advert, name)]
    by_hardware_id = [advert for advert in adverts if same_hardware_id(advert.hardware_id, name)]
    matches = by_hardware_id or by_label
    if not matches:
        return None
    if len(rigs := _network_infos(matches)) > 1:
        raise AmbiguousRigError(
            _with_table(
                f"{len(rigs)} Rigs on the network are labelled {name!r}; pass Rig.connect() the "
                "Hardware ID or tcp://host:port of one:",
                rigs,
            )
        )
    advert = matches[0]
    release(tcp_endpoint((advert.address, advert.port)))  # A Rig this process connected to there.
    connection = Connection.open(TcpTransport(advert.address, advert.port))
    try:
        _check_identity(connection, advert, None if by_hardware_id else name)
        if log_level is not None:
            connection.set_log_level(log_level)
    except BaseException:
        connection.close()
        raise
    return connection


def _check_identity(connection: Connection, advert: _mdns.Advert, label: str | None) -> None:
    """Checks the Rig's `Hello` names the Rig `advert` advertises, labelled `label` in full.

    The instance name holds only the first 63 bytes of a Label, and two Rigs may advertise the
    same one, so the TXT a lookup heard may not be this Rig's.
    """
    if not same_hardware_id(connection.hardware_id, advert.hardware_id):
        raise ItchError(
            f"The Rig at {advert.url} says its Hardware ID is {connection.hardware_id}, but it "
            f"advertises {advert.hardware_id.upper()}. Another Rig on the network may advertise "
            "the same label; pass Rig.connect() a Hardware ID or tcp://host:port."
        )
    if label is not None and connection.hello.label.casefold() != label.casefold():
        raise RigNotFoundError(
            f"Rig {label!r} not found: the Rig advertising it at {advert.url} is labelled "
            f"{connection.hello.label!r}."
        )


def _network_infos(adverts: Iterable[_mdns.Advert]) -> list[RigInfo]:
    """One `RigInfo` per Hardware ID among `adverts`."""
    rigs: dict[str, RigInfo] = {}
    for advert in adverts:
        rigs.setdefault(
            advert.hardware_id.upper(),
            RigInfo(advert.url, advert.hardware_id.upper(), advert.instance, None, transport="tcp"),
        )
    return list(rigs.values())


def _advertises_label(advert: _mdns.Advert, label: str) -> bool:
    return advert.instance.casefold() == _mdns.advertised(label).casefold()


def _open(port: UsbPort, log_level: int | None) -> Connection:
    """Connects to the Rig on `port`, first disconnecting a Rig this process has connected
    there, which would hold the port."""
    release(usb_endpoint(port.device))
    try:
        return _connect(port, log_level)
    except PortInUse:
        raise RigNotFoundError(
            f"Rig {port.hardware_id} on {port.device} is in use by another program."
        ) from None


def _held_info(port: UsbPort, connection: Connection) -> RigInfo | None:
    """The Rig this process has connected on `port`, asked its Label again over `connection`,
    since another connection may have renamed it, without disturbing its Rig.

    `None` if the connection has dropped, as after a reboot, after closing it so the port can be
    probed. Its Rig stays registered, so connecting there again still says it was replaced.
    """
    try:
        connection.name = connection.request(_wire.Hello(), _wire.HelloReply).label
    except DisconnectedError:
        connection.close()
        return None
    except ItchError as err:
        return RigInfo(port.device, connection.hardware_id, None, None, str(err))
    firmware_version = connection.hello.firmware_version
    return RigInfo(port.device, connection.hardware_id, connection.name, firmware_version)


def _probe(port: UsbPort) -> tuple[Connection | None, RigInfo]:
    """Connects to a Rig to ask who it is, leaving it open. `None` if it is in use or fails."""
    try:
        connection = _connect(port, None)
    except PortInUse:
        return None, RigInfo(port.device, port.hardware_id, None, None)
    except ItchError as err:
        return None, RigInfo(port.device, port.hardware_id, None, None, str(err))
    hello = connection.hello
    info = RigInfo(port.device, connection.hardware_id, hello.label, hello.firmware_version)
    return connection, info


def _connect(port: UsbPort, log_level: int | None) -> Connection:
    """Connects to the Rig on `port`, checking its `Hello` names the Rig the port lists.

    Raises `PortInUse` if another program has the port open.
    """
    transport = UsbTransport(port.device)
    return Connection.open(transport, hardware_id=port.hardware_id, log_level=log_level)


def _info(port: UsbPort) -> RigInfo:
    connection, info = _probe(port)
    if connection is not None:
        connection.close()
    return info


def _same_label(info: RigInfo, label: str) -> bool:
    return info.label is not None and info.label.casefold() == label.casefold()


def _with_table(message: str, rigs: list[RigInfo]) -> str:
    return "\n  ".join([message, *rig_table(rigs)])
