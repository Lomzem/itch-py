"""Finding Rigs plugged in over USB: picking one by name, and listing them."""

from __future__ import annotations

import dataclasses
import os
import sys
from collections.abc import Iterable

from itch._connection import Connection, same_hardware_id
from itch._errors import AmbiguousRigError, ItchError, RigNotFoundError
from itch._usb import PortInUse, UsbPort, UsbTransport, usb_ports


@dataclasses.dataclass(frozen=True)
class RigInfo:
    """A Rig plugged in over USB, as `list_rigs()` finds it."""

    port: str
    """Such as `COM4` or `/dev/ttyACM0`."""
    hardware_id: str
    """Such as `60:55:F9:C0:27:18`."""
    label: str | None
    """Such as `bench3`, or `None` if the Rig is in use or failed."""
    firmware_version: str | None
    """Such as `1.0.0`, or `None` if the Rig is in use or failed."""
    error: str | None = None
    """Why itch-py couldn't ask a free Rig its label, such as a protocol mismatch."""

    @property
    def in_use(self) -> bool:
        """Whether another program has the Rig open, so itch-py couldn't ask its label."""
        return self.label is None and self.error is None


def rig_infos() -> list[RigInfo]:
    """The Rigs plugged in over USB, each opened briefly unless in use."""
    return [_info(port) for port in usb_ports()]


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


def find_rig(name: str | None, log_level: int | None) -> Connection:
    """Connects to the USB Rig `name` picks: by port, then Hardware ID, then label."""
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
        if _same_port(port.device, name):
            return _open(port, log_level)
    for port in ports:
        if same_hardware_id(port.hardware_id, name):
            return _open(port, log_level)
    return _find_label(ports, name, log_level)


def _find_label(ports: list[UsbPort], label: str, log_level: int | None) -> Connection:
    """Connects to every free Rig to find the one labelled `label`, and closes the rest."""
    found: list[RigInfo] = []
    matches: list[Connection] = []
    try:
        for port in ports:
            connection, info = _probe(port)
            found.append(info)
            if connection is None:
                continue
            if _same_label(info, label):
                matches.append(connection)
            else:
                connection.close()
        if len(matches) == 1:
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


def _open(port: UsbPort, log_level: int | None) -> Connection:
    try:
        return _connect(port, log_level)
    except PortInUse:
        raise RigNotFoundError(
            f"Rig {port.hardware_id} on {port.device} is in use by another program."
        ) from None


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


def _same_port(device: str, name: str) -> bool:
    if sys.platform == "win32":
        return device.casefold() == name.casefold()
    return os.path.realpath(device) == os.path.realpath(name)  # Such as /dev/serial/by-id/…


def _same_label(info: RigInfo, label: str) -> bool:
    return info.label is not None and info.label.casefold() == label.casefold()


def _with_table(message: str, rigs: list[RigInfo]) -> str:
    return "\n  ".join([message, *rig_table(rigs)])
