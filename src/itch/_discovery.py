"""Finding Rigs plugged in over USB: picking one by name, and listing them."""

from __future__ import annotations

import dataclasses
import os
import sys
from collections.abc import Iterable
from typing import TYPE_CHECKING, TypeVar

from itch._errors import AmbiguousRigError, ItchError, RigNotFoundError
from itch._usb import PortInUse, UsbPort, UsbTransport, usb_ports

if TYPE_CHECKING:
    from itch._rig import Rig

_Rig = TypeVar("_Rig", bound="Rig")


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


def rig_infos(cls: type[Rig]) -> list[RigInfo]:
    """The Rigs plugged in over USB, each opened briefly as a `cls` unless in use."""
    return [_info(cls, port) for port in usb_ports()]


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


def find_rig(cls: type[_Rig], name: str | None, log_level: int | None) -> _Rig:
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
