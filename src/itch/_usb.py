"""Rigs on USB: finding their ports, and talking to them over USB serial."""

from __future__ import annotations

import dataclasses
import errno
import sys

import serial
from serial.tools import list_ports

from itch._endpoints import usb_endpoint
from itch._errors import ItchError
from itch._transport import Disconnected, StreamTransport

VID, PID = 0x303A, 0x1001
"""The ESP32-S3's USB Serial/JTAG, which every Rig shows as."""

_READ_TIMEOUT = 0.05
"""Seconds each port read waits. It is fixed at open, since changing it touches the lines."""

_WRITE_TIMEOUT = 2.0


class PortInUse(Exception):
    """Another program has the port open."""


@dataclasses.dataclass(frozen=True)
class UsbPort:
    device: str
    """Such as `COM4` or `/dev/ttyACM0`."""
    hardware_id: str
    """The USB serial number, which is the Hardware ID, such as `60:55:F9:C0:27:18`."""


def usb_ports() -> list[UsbPort]:
    """The Rigs plugged in over USB, found without opening any port."""
    return [
        UsbPort(port.device, (port.serial_number or "").upper())
        for port in list_ports.comports()
        if (port.vid, port.pid) == (VID, PID)
    ]


class UsbTransport(StreamTransport):
    def __init__(self, device: str) -> None:
        """Opens `device` for this process alone. Raises `PortInUse` if another program has it."""
        super().__init__(device)
        self.endpoint = usb_endpoint(device)
        # The S3 resets on RTS without DTR, and sets its download flag on DTR without RTS.
        # Linux raises both lines on open and pySerial then applies DTR before RTS, so keep both
        # up there. On Windows keep both down, as esptool does. Never touch them again.
        lines = sys.platform != "win32"
        self._serial = serial.Serial(
            baudrate=115200, timeout=_READ_TIMEOUT, write_timeout=_WRITE_TIMEOUT, exclusive=True
        )
        self._serial.dtr = self._serial.rts = lines
        self._serial.port = device
        try:
            self._serial.open()
        except serial.SerialException as err:
            # Windows opens ports for one program only. On Linux, `exclusive` is a lock that
            # every itch-py takes; it is taken before pySerial sets the lines.
            if sys.platform == "win32" or err.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise PortInUse(device) from err
            hint = (
                " Add yourself to the group that owns it, often dialout or uucp, and log in again."
                if err.errno == errno.EACCES
                else ""
            )
            raise ItchError(f"Can't open {device}: {err}.{hint}") from err

    def close(self) -> None:
        self._serial.close()

    def _wake(self) -> None:
        self._serial.cancel_read()

    def _write(self, data: bytes) -> None:
        try:
            self._serial.write(data)
        except (serial.SerialException, OSError) as err:
            raise Disconnected from err

    def _read(self) -> bytes:
        try:
            return self._serial.read(self._serial.in_waiting or 1)
        except (serial.SerialException, OSError) as err:
            raise Disconnected from err
