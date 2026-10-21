"""The payload codec: the message envelope and every message body.

Private: QA never import it. The layouts follow the byte tables in the `itch` protocol docs, and
body field names match them, as the conformance vectors do. Decoding is strict: exact sizes, no
trailing bytes, valid bools and UTF-8, and text within its limit.

Adding a message means a `RequestType` value, a request body and a reply body here (each with
`TYPE`, `encode` and `decode`), entries in `RequestBody`, `ReplyBody` and the two registries, and
the type in the vector test's name maps. An Event is a dataclass with `TYPE`, `encode` and
`decode`, an entry in `_EVENTS` and the `Message` union, and the Event name map.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar, Self

PROTOCOL = 3
"""Bumped on any message change. A Rig must report exactly this."""

MAX_LABEL = 64
"""The longest Label text, in bytes."""

MAX_HOLDER = 64
"""The longest Holder text, in bytes."""

MAX_SSID = 32
"""The longest Wi-Fi SSID, in bytes."""

MIN_PASSPHRASE = 8
MAX_PASSPHRASE = 63
"""A Wi-Fi passphrase is 8 to 63 bytes, or empty to clear the credentials."""

MAX_LAST_PANIC = 64
"""The longest `last_panic` text, in bytes."""

LINK_CONNECTED = 2
"""`GetStatus` `link` runs from 0 off through 1 joining to 2 connected."""

ADDRESS_STATIC = 1
"""`mode` is 0 DHCP or 1 static."""

LOG_LEVEL_DEBUG = 4
"""Rig log levels run from 0 off through 1 error, 2 warn and 3 info to 4 debug."""

MAX_LOG_TEXT = 1024 - 6
"""The longest Log Event text: the payload cap less `type`, `level` and `dropped`."""

_RESPONSE_BIT = 0x80
_FIRST_EVENT_TYPE = 0x40
_STATUS_OK = 0
_MAX_TEXT = 0xFF


class RequestType(IntEnum):
    """The `type` byte of a request; its response's is `type | 0x80`."""

    Hello = 0x01
    GetChannels = 0x02
    WriteChannels = 0x03
    Clear = 0x04
    GetStatus = 0x05
    SetLabel = 0x06
    SetLogLevel = 0x07
    Lock = 0x0B
    ReleaseLock = 0x0C
    SetWifi = 0x0D
    SetAddress = 0x0E


class ErrorCode(IntEnum):
    """A non-zero response `status`. Rigs may send codes not listed here."""

    UnknownRequest = 1
    Malformed = 3
    Busy = 7
    HardwareFault = 8
    StorageFault = 9
    Internal = 10
    Locked = 11


class DecodeError(ValueError):
    """A payload breaks its byte table."""


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def _unpack(self, fmt: struct.Struct) -> int:
        if self._pos + fmt.size > len(self._data):
            raise DecodeError("body too short")
        (value,) = fmt.unpack_from(self._data, self._pos)
        self._pos += fmt.size
        return value

    def u8(self) -> int:
        return self._unpack(_U8)

    def u16(self) -> int:
        return self._unpack(_U16)

    def u32(self) -> int:
        return self._unpack(_U32)

    def u64(self) -> int:
        return self._unpack(_U64)

    def bool(self) -> bool:
        value = self.u8()
        if value > 1:
            raise DecodeError(f"bool is {value}, not 0 or 1")
        return value == 1

    def raw(self, size: int) -> bytes:
        if self._pos + size > len(self._data):
            raise DecodeError("body too short")
        self._pos += size
        return self._data[self._pos - size : self._pos]

    def text(self, max_len: int = _MAX_TEXT) -> str:
        """A `u8` length, then that many bytes of UTF-8, at most `max_len` of them."""
        size = self.u8()
        if size > max_len:
            raise DecodeError(f"text is {size} bytes, over {max_len}")
        try:
            return self.raw(size).decode("utf-8")
        except UnicodeDecodeError as err:
            raise DecodeError("text isn't valid UTF-8") from err

    def ipv4(self) -> bytes:
        """An IPv4 address: 4 bytes in network order."""
        return self.raw(4)

    def mode(self) -> int:
        """An address `mode`: 0 DHCP or 1 static."""
        mode = self.u8()
        if mode > ADDRESS_STATIC:
            raise DecodeError(f"address mode is {mode}, not 0 DHCP or 1 static")
        return mode

    def rest(self) -> bytes:
        self._pos, start = len(self._data), self._pos
        return self._data[start:]

    def finish(self) -> None:
        if self._pos != len(self._data):
            raise DecodeError(f"{len(self._data) - self._pos} bytes left over")


class _Writer:
    def __init__(self) -> None:
        self._out = bytearray()

    def u8(self, value: int) -> None:
        self._out += _U8.pack(value)

    def u16(self, value: int) -> None:
        self._out += _U16.pack(value)

    def u32(self, value: int) -> None:
        self._out += _U32.pack(value)

    def u64(self, value: int) -> None:
        self._out += _U64.pack(value)

    def bool(self, value: bool) -> None:
        self.u8(int(value))

    def raw(self, data: bytes) -> None:
        self._out += data

    def ipv4(self, address: bytes) -> None:
        if len(address) != 4:
            raise ValueError(f"an IPv4 address is 4 bytes, not {len(address)}")
        self.raw(address)

    def text(self, text: str, max_len: int = _MAX_TEXT) -> None:
        data = text.encode("utf-8")
        if len(data) > max_len:
            raise ValueError(f"text is {len(data)} bytes, over {max_len}")
        self.u8(len(data))
        self.raw(data)

    def getvalue(self) -> bytes:
        return bytes(self._out)


_U8 = struct.Struct("<B")
_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")


# --- Hello -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hello:
    TYPE: ClassVar[RequestType] = RequestType.Hello

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


@dataclass(frozen=True)
class HelloReply:
    TYPE: ClassVar[RequestType] = RequestType.Hello

    protocol: int
    firmware_version: str
    dirty: bool
    channel_count: int
    board_revision: str
    hardware_id: bytes
    label: str

    def encode(self, w: _Writer) -> None:
        w.u16(self.protocol)
        w.text(self.firmware_version)
        w.bool(self.dirty)
        w.u8(self.channel_count)
        w.text(self.board_revision)
        w.raw(self.hardware_id)
        w.text(self.label, MAX_LABEL)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(
            protocol=r.u16(),
            firmware_version=r.text(),
            dirty=r.bool(),
            channel_count=r.u8(),
            board_revision=r.text(),
            hardware_id=r.raw(6),
            label=r.text(MAX_LABEL),
        )


# --- Channels ----------------------------------------------------------------------------------
# A Channel state is a `u16`, bit 0 = CH1, with a set bit meaning on.


@dataclass(frozen=True)
class GetChannels:
    TYPE: ClassVar[RequestType] = RequestType.GetChannels

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


@dataclass(frozen=True)
class GetChannelsReply:
    TYPE: ClassVar[RequestType] = RequestType.GetChannels

    state: int
    """The commanded state."""

    def encode(self, w: _Writer) -> None:
        w.u16(self.state)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(state=r.u16())


@dataclass(frozen=True)
class WriteChannels:
    """A Mask write: Channels whose `mask` bit is set take their `values` bit."""

    TYPE: ClassVar[RequestType] = RequestType.WriteChannels

    holder: str
    """Empty = no Holder."""
    mask: int
    values: int

    def encode(self, w: _Writer) -> None:
        w.text(self.holder, MAX_HOLDER)
        w.u16(self.mask)
        w.u16(self.values)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(holder=r.text(MAX_HOLDER), mask=r.u16(), values=r.u16())


@dataclass(frozen=True)
class WriteChannelsReply:
    TYPE: ClassVar[RequestType] = RequestType.WriteChannels

    state: int
    """The state after settling."""

    def encode(self, w: _Writer) -> None:
        w.u16(self.state)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(state=r.u16())


@dataclass(frozen=True)
class Clear:
    TYPE: ClassVar[RequestType] = RequestType.Clear

    holder: str
    """Empty = no Holder."""

    def encode(self, w: _Writer) -> None:
        w.text(self.holder, MAX_HOLDER)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(holder=r.text(MAX_HOLDER))


@dataclass(frozen=True)
class ClearReply:
    TYPE: ClassVar[RequestType] = RequestType.Clear

    state: int
    """The state after settling."""

    def encode(self, w: _Writer) -> None:
        w.u16(self.state)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(state=r.u16())


# --- Status ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class GetStatus:
    TYPE: ClassVar[RequestType] = RequestType.GetStatus

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


@dataclass(frozen=True)
class GetStatusReply:
    """The Rig's health, Lock and network. Decoding rejects fields that contradict each other."""

    TYPE: ClassVar[RequestType] = RequestType.GetStatus

    uptime_ms: int
    reset_reason: int
    """The raw ESP32-S3 `SocResetReason`, or 0 if unknown."""
    last_panic: str
    """Empty = no panic."""
    crc_failures: int
    oversized_frames: int
    malformed_frames: int
    dropped_logs: int
    expander_faults: int
    usb_tx_dropped: int
    holder: str
    """Who holds the Lock. Empty = unlocked."""
    wifi_configured: bool
    ssid: str
    """Empty exactly when `wifi_configured` is false. The passphrase is never reported."""
    link: int
    """0 off, 1 joining or 2 connected."""
    current_address: bytes
    """Non-zero exactly when connected."""
    mode: int
    """0 DHCP or 1 static, with `address`, `prefix` and `gateway` as `SetAddress` takes them."""
    address: bytes
    prefix: int
    gateway: bytes

    def encode(self, w: _Writer) -> None:
        w.u64(self.uptime_ms)
        w.u8(self.reset_reason)
        w.text(self.last_panic, MAX_LAST_PANIC)
        w.u32(self.crc_failures)
        w.u32(self.oversized_frames)
        w.u32(self.malformed_frames)
        w.u32(self.dropped_logs)
        w.u32(self.expander_faults)
        w.u32(self.usb_tx_dropped)
        w.text(self.holder, MAX_HOLDER)
        w.bool(self.wifi_configured)
        w.text(self.ssid, MAX_SSID)
        w.u8(self.link)
        w.ipv4(self.current_address)
        w.u8(self.mode)
        w.ipv4(self.address)
        w.u8(self.prefix)
        w.ipv4(self.gateway)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        status = cls(
            uptime_ms=r.u64(),
            reset_reason=r.u8(),
            last_panic=r.text(MAX_LAST_PANIC),
            crc_failures=r.u32(),
            oversized_frames=r.u32(),
            malformed_frames=r.u32(),
            dropped_logs=r.u32(),
            expander_faults=r.u32(),
            usb_tx_dropped=r.u32(),
            holder=r.text(MAX_HOLDER),
            wifi_configured=r.bool(),
            ssid=r.text(MAX_SSID),
            link=r.u8(),
            current_address=r.ipv4(),
            mode=r.mode(),
            address=r.ipv4(),
            prefix=r.u8(),
            gateway=r.ipv4(),
        )
        if status.link > LINK_CONNECTED:
            raise DecodeError(f"link is {status.link}, not 0 off, 1 joining or 2 connected")
        if status.wifi_configured == (status.ssid == ""):
            raise DecodeError("wifi_configured disagrees with the SSID")
        if not status.wifi_configured and status.link:
            raise DecodeError("the link is up without Wi-Fi credentials")
        if (status.link == LINK_CONNECTED) != (status.current_address != _ZERO_ADDRESS):
            raise DecodeError("current_address disagrees with the link")
        _check_addressing(status.mode, status.address, status.prefix, status.gateway)
        return status


# --- SetLogLevel and the Log Event ------------------------------------------------------------


@dataclass(frozen=True)
class SetLabel:
    TYPE: ClassVar[RequestType] = RequestType.SetLabel

    holder: str
    """Empty = no Holder."""
    label: str

    def encode(self, w: _Writer) -> None:
        w.text(self.holder, MAX_HOLDER)
        w.text(self.label, MAX_LABEL)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(holder=r.text(MAX_HOLDER), label=r.text(MAX_LABEL))


@dataclass(frozen=True)
class SetLabelReply:
    TYPE: ClassVar[RequestType] = RequestType.SetLabel

    label: str

    def encode(self, w: _Writer) -> None:
        w.text(self.label, MAX_LABEL)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(label=r.text(MAX_LABEL))


def _log_level(r: _Reader, lowest: int) -> int:
    level = r.u8()
    if not lowest <= level <= LOG_LEVEL_DEBUG:
        raise DecodeError(f"log level {level} isn't {lowest} to {LOG_LEVEL_DEBUG}")
    return level


@dataclass(frozen=True)
class SetLogLevel:
    TYPE: ClassVar[RequestType] = RequestType.SetLogLevel

    level: int

    def encode(self, w: _Writer) -> None:
        w.u8(self.level)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(level=_log_level(r, 0))


@dataclass(frozen=True)
class SetLogLevelReply:
    TYPE: ClassVar[RequestType] = RequestType.SetLogLevel

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


@dataclass(frozen=True)
class LogEvent:
    """One line of the Rig's log. `text` runs to the end of the payload."""

    TYPE: ClassVar[int] = 0x40

    level: int
    """1 error to 4 debug."""
    dropped: int
    """Log Events the Rig dropped for this connection since the last one sent."""
    text: str

    def encode(self, w: _Writer) -> None:
        w.u8(self.level)
        w.u32(self.dropped)
        data = self.text.encode("utf-8")
        if len(data) > MAX_LOG_TEXT:
            raise ValueError(f"log text is {len(data)} bytes, over {MAX_LOG_TEXT}")
        w.raw(data)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        level, dropped = _log_level(r, 1), r.u32()
        try:
            text = r.rest().decode("utf-8")
        except UnicodeDecodeError as err:
            raise DecodeError("log text isn't valid UTF-8") from err
        return cls(level=level, dropped=dropped, text=text)


# --- Lock -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Lock:
    TYPE: ClassVar[RequestType] = RequestType.Lock

    holder: str
    """Never empty."""
    takeover: bool
    """Take the Lock from another Holder."""

    def encode(self, w: _Writer) -> None:
        w.text(self.holder, MAX_HOLDER)
        w.bool(self.takeover)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        if not (holder := r.text(MAX_HOLDER)):
            raise DecodeError("Lock has an empty holder")
        return cls(holder=holder, takeover=r.bool())


@dataclass(frozen=True)
class LockReply:
    TYPE: ClassVar[RequestType] = RequestType.Lock

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


@dataclass(frozen=True)
class ReleaseLock:
    TYPE: ClassVar[RequestType] = RequestType.ReleaseLock

    holder: str

    def encode(self, w: _Writer) -> None:
        w.text(self.holder, MAX_HOLDER)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(holder=r.text(MAX_HOLDER))


@dataclass(frozen=True)
class ReleaseLockReply:
    TYPE: ClassVar[RequestType] = RequestType.ReleaseLock

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


# --- Wi-Fi and address -------------------------------------------------------------------------
# IPv4 addresses are 4 bytes in network order, zero meaning none.

_ZERO_ADDRESS = bytes(4)


@dataclass(frozen=True)
class SetWifi:
    """Gives the Rig Wi-Fi credentials, or clears them with an empty `ssid` and `passphrase`."""

    TYPE: ClassVar[RequestType] = RequestType.SetWifi

    holder: str
    """Empty = no Holder."""
    ssid: str
    """1 to 32 bytes, or empty to clear the credentials."""
    passphrase: str
    """8 to 63 bytes, or empty with an empty `ssid`."""

    def encode(self, w: _Writer) -> None:
        w.text(self.holder, MAX_HOLDER)
        w.text(self.ssid, MAX_SSID)
        w.text(self.passphrase, MAX_PASSPHRASE)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        wifi = cls(
            holder=r.text(MAX_HOLDER), ssid=r.text(MAX_SSID), passphrase=r.text(MAX_PASSPHRASE)
        )
        clears = wifi.ssid == wifi.passphrase == ""
        if not clears and (not wifi.ssid or len(wifi.passphrase.encode()) < MIN_PASSPHRASE):
            raise DecodeError("SetWifi needs an SSID and an 8 to 63 byte passphrase, or neither")
        return wifi


@dataclass(frozen=True)
class SetWifiReply:
    TYPE: ClassVar[RequestType] = RequestType.SetWifi

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


@dataclass(frozen=True)
class SetAddress:
    """Sets DHCP, with every other field zero, or a static address, prefix and gateway."""

    TYPE: ClassVar[RequestType] = RequestType.SetAddress

    holder: str
    """Empty = no Holder."""
    mode: int
    """0 DHCP or 1 static."""
    address: bytes
    """Static: unicast. DHCP: zero."""
    prefix: int
    """Static: 1 to 32. DHCP: zero."""
    gateway: bytes
    """Static: zero for none, or unicast. DHCP: zero."""

    def encode(self, w: _Writer) -> None:
        w.text(self.holder, MAX_HOLDER)
        w.u8(self.mode)
        w.ipv4(self.address)
        w.u8(self.prefix)
        w.ipv4(self.gateway)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        address = cls(
            holder=r.text(MAX_HOLDER),
            mode=r.mode(),
            address=r.ipv4(),
            prefix=r.u8(),
            gateway=r.ipv4(),
        )
        _check_addressing(address.mode, address.address, address.prefix, address.gateway)
        return address


@dataclass(frozen=True)
class SetAddressReply:
    TYPE: ClassVar[RequestType] = RequestType.SetAddress

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


def is_unicast(address: bytes) -> bool:
    """Whether `address` is unicast: not zero, not 255.255.255.255 and not multicast."""
    return address not in (_ZERO_ADDRESS, b"\xff" * 4) and not 224 <= address[0] <= 239


def _check_addressing(mode: int, address: bytes, prefix: int, gateway: bytes) -> None:
    """Raises `DecodeError` unless the fields are a configuration `SetAddress` could give."""
    if mode == ADDRESS_STATIC:
        valid = (
            is_unicast(address)
            and 1 <= prefix <= 32
            and (gateway == _ZERO_ADDRESS or is_unicast(gateway))
        )
    else:
        valid = address == gateway == _ZERO_ADDRESS and prefix == 0
    if not valid:
        raise DecodeError("the address configuration isn't one SetAddress could give")


# --- Envelope ----------------------------------------------------------------------------------

RequestBody = (
    Hello
    | GetChannels
    | WriteChannels
    | Clear
    | GetStatus
    | SetLabel
    | SetLogLevel
    | Lock
    | ReleaseLock
    | SetWifi
    | SetAddress
)
ReplyBody = (
    HelloReply
    | GetChannelsReply
    | WriteChannelsReply
    | ClearReply
    | GetStatusReply
    | SetLabelReply
    | SetLogLevelReply
    | LockReply
    | ReleaseLockReply
    | SetWifiReply
    | SetAddressReply
)

_REQUESTS: dict[int, type[RequestBody]] = {
    cls.TYPE: cls
    for cls in (
        Hello,
        GetChannels,
        WriteChannels,
        Clear,
        GetStatus,
        SetLabel,
        SetLogLevel,
        Lock,
        ReleaseLock,
        SetWifi,
        SetAddress,
    )
}
_REPLIES: dict[int, type[ReplyBody]] = {
    cls.TYPE: cls
    for cls in (
        HelloReply,
        GetChannelsReply,
        WriteChannelsReply,
        ClearReply,
        GetStatusReply,
        SetLabelReply,
        SetLogLevelReply,
        LockReply,
        ReleaseLockReply,
        SetWifiReply,
        SetAddressReply,
    )
}
_EVENTS: dict[int, type[LogEvent]] = {cls.TYPE: cls for cls in (LogEvent,)}


@dataclass(frozen=True)
class Request:
    request_id: int
    body: RequestBody


@dataclass(frozen=True)
class OkResponse:
    request_id: int
    body: ReplyBody


@dataclass(frozen=True)
class ErrorResponse:
    request_type: int
    """The raw request type, so an unknown request can be echoed."""
    request_id: int
    code: int
    """An `ErrorCode`, or a code this client doesn't know."""
    detail: str


@dataclass(frozen=True)
class UnknownEvent:
    """An Event this client doesn't know. Clients ignore them."""

    type: int
    body: bytes


Message = Request | OkResponse | ErrorResponse | LogEvent | UnknownEvent


def encode(message: Message) -> bytes:
    w = _Writer()
    match message:
        case Request(request_id, body):
            w.u8(body.TYPE)
            w.u32(request_id)
            body.encode(w)
        case OkResponse(request_id, body):
            w.u8(body.TYPE | _RESPONSE_BIT)
            w.u32(request_id)
            w.u8(_STATUS_OK)
            body.encode(w)
        case ErrorResponse(request_type, request_id, code, detail):
            w.u8(request_type | _RESPONSE_BIT)
            w.u32(request_id)
            w.u8(code)
            w.text(detail)
        case LogEvent():
            w.u8(message.TYPE)
            message.encode(w)
        case UnknownEvent(type_, body):
            w.u8(type_)
            w.raw(body)
    return w.getvalue()


def hello_protocol(payload: bytes, request_id: int) -> int | None:
    """The `protocol` an ok `Hello` reply to `request_id` starts with, before the rest is decoded.

    `None` if `payload` isn't such a reply. Every protocol puts `protocol` first, so this reads
    it even from a body that doesn't decode as this protocol's.
    """
    r = _Reader(payload)
    try:
        if (r.u8(), r.u32(), r.u8()) != (RequestType.Hello | _RESPONSE_BIT, request_id, _STATUS_OK):
            return None
        return r.u16()
    except DecodeError:
        return None


def decode(payload: bytes) -> Message:
    """Decodes one payload. Raises `DecodeError` if it breaks its byte table."""
    r = _Reader(payload)
    type_ = r.u8()
    message: Message
    if _FIRST_EVENT_TYPE <= type_ < _RESPONSE_BIT:
        if not (event := _EVENTS.get(type_)):
            return UnknownEvent(type_, payload[1:])
        return event.decode(r)
    request_id = r.u32()
    if type_ & _RESPONSE_BIT:
        request_type = type_ & ~_RESPONSE_BIT
        status = r.u8()
        if status != _STATUS_OK:
            message = ErrorResponse(request_type, request_id, status, r.text())
        elif reply := _REPLIES.get(request_type):
            message = OkResponse(request_id, reply.decode(r))
        else:
            raise DecodeError(f"ok reply to unknown request type 0x{request_type:02x}")
    elif request := _REQUESTS.get(type_):
        message = Request(request_id, request.decode(r))
    else:
        raise DecodeError(f"unknown request type 0x{type_:02x}")
    r.finish()
    return message
