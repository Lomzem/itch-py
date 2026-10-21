"""A stubbed USB bench: a port list for `comports()` and a fake `serial.Serial` behind it.

It isn't a Rig: a free port answers `Hello` with a scripted reply, grants `SetLogLevel`,
`Lock` and `ReleaseLock`, and records what itch-py did to it.
"""

from __future__ import annotations

import dataclasses
import errno
import os
import sys
import threading
from typing import Any

import pytest
import serial
from scripted_rig import ACME_HELLO
from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

from itch._frame import FrameDecoder, encode_frame
from itch._wire import (
    Hello,
    HelloReply,
    Lock,
    LockReply,
    OkResponse,
    ReleaseLock,
    ReleaseLockReply,
    Request,
    SetLogLevel,
    SetLogLevelReply,
    decode,
    encode,
)

ESPRESSIF_VID, USB_SERIAL_JTAG_PID = 0x303A, 0x1001

Event = tuple[str, Any]


@dataclasses.dataclass
class FakePort:
    device: str
    hardware_id: str
    hello: HelloReply | None
    """What the Rig answers to `Hello`, or `None` while another program has the port open."""
    events: list[Event] = dataclasses.field(default_factory=list[Event])
    """What itch-py did to the port, in order, such as `("dtr", True)` or `("open", True)`.

    `("open", exclusive)` records whether the open asked for exclusive access.
    """
    requests: list[Request] = dataclasses.field(default_factory=list[Request])
    open_errno: int | None = None
    """Set to make opening fail as the OS would, such as with `errno.EACCES`."""

    @property
    def opened(self) -> bool:
        return any(name == "open" for name, _ in self.events)


class FakeBench:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.ports: dict[str, FakePort] = {}
        self.other_devices: list[ListPortInfo] = []
        """Serial ports that aren't Rigs."""
        bench = self

        class FakeSerial(_FakeSerial):
            def __init__(self, port: str | None = None, **settings: Any) -> None:
                super().__init__(bench, port, **settings)

        monkeypatch.setattr(list_ports, "comports", self._comports)
        monkeypatch.setattr(serial, "Serial", FakeSerial)

    def rig(
        self, device: str, hardware_id: str, label: str = "", *, in_use: bool = False
    ) -> FakePort:
        """Plugs in a Rig, labelled `label` (by default `itch-` plus its Hardware ID's end)."""
        raw = bytes.fromhex(hardware_id.replace(":", ""))
        hello = dataclasses.replace(
            ACME_HELLO, hardware_id=raw, label=label or f"itch-{raw[3:].hex().upper()}"
        )
        port = FakePort(device, hardware_id, None if in_use else hello)
        self.ports[device] = port
        return port

    def _comports(self, include_links: bool = False) -> list[ListPortInfo]:
        found: list[ListPortInfo] = []
        for port in self.ports.values():
            info = ListPortInfo(port.device, skip_link_detection=True)
            info.vid, info.pid = ESPRESSIF_VID, USB_SERIAL_JTAG_PID
            info.serial_number = port.hardware_id
            found.append(info)
        return found + self.other_devices


class _FakeSerial:
    def __init__(self, bench: FakeBench, port: str | None, **settings: Any) -> None:
        self._bench = bench
        self._events: list[Event] = []
        self._target: FakePort | None = None
        self._decoder = FrameDecoder()
        self._out = bytearray()
        self._replied = threading.Condition()
        self.port = port
        self.exclusive = settings.pop("exclusive", None)
        self.settings = settings
        self.is_open = False
        if port is not None:
            self.open()

    @property
    def dtr(self) -> bool:
        raise AssertionError("itch-py reads DTR")

    @dtr.setter
    def dtr(self, value: bool) -> None:
        self._events.append(("dtr", value))

    @property
    def rts(self) -> bool:
        raise AssertionError("itch-py reads RTS")

    @rts.setter
    def rts(self, value: bool) -> None:
        self._events.append(("rts", value))

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("baudrate", "timeout", "write_timeout") and self.__dict__.get("is_open"):
            self._events.append(("reconfigure", name))  # pySerial reapplies DTR/RTS on Windows.
        object.__setattr__(self, name, value)

    def open(self) -> None:
        port = self._bench.ports[self.port or ""]
        port.events += self._events
        self._events = port.events
        if port.hello is None:
            if sys.platform == "win32":
                raise serial.SerialException(
                    f"could not open port {port.device!r}: PermissionError(13, 'Access is denied.')"
                )
            raise serial.SerialException(
                errno.EAGAIN, f"Could not exclusively lock port {port.device}: [Errno 11]"
            )
        if port.open_errno is not None:
            reason = os.strerror(port.open_errno)
            raise serial.SerialException(
                port.open_errno,
                f"could not open port {port.device}: [Errno {port.open_errno}] {reason}",
            )
        self._events.append(("open", self.exclusive))
        self._target = port
        self.is_open = True

    @property
    def in_waiting(self) -> int:
        return len(self._out)

    def write(self, data: bytes) -> int:
        assert self._target is not None
        assert self._target.hello is not None
        for payload in self._decoder.feed(data):
            request = decode(payload)
            assert isinstance(request, Request)
            self._target.requests.append(request)
            match request.body:
                case Hello():
                    reply = OkResponse(request.request_id, self._target.hello)
                case SetLogLevel():
                    reply = OkResponse(request.request_id, SetLogLevelReply())
                case Lock():
                    reply = OkResponse(request.request_id, LockReply())
                case ReleaseLock():
                    reply = OkResponse(request.request_id, ReleaseLockReply())
                case other:
                    raise AssertionError(f"the fake bench can't answer {other}")
            with self._replied:
                self._out += encode_frame(encode(reply))
                self._replied.notify_all()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        """Returns up to `size` bytes, waiting up to the read timeout for some, as pySerial does."""
        with self._replied:
            self._replied.wait_for(lambda: self._out, self.settings["timeout"])
            data = bytes(self._out[:size])
            del self._out[:size]
        return data

    def close(self) -> None:
        if self.is_open:
            self._events.append(("close", None))
        self.is_open = False
