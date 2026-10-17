"""The payload codec: the message envelope and every message body.

Private: QA never import it. The layouts follow the byte tables in the `itch` protocol docs, and
body field names match them, as the conformance vectors do. Decoding is strict: exact sizes, no
trailing bytes, valid bools and UTF-8, and text within its limit.

Adding a message means a `RequestType` value, a request body and a reply body here (each with
`TYPE`, `encode` and `decode`), entries in `RequestBody`, `ReplyBody` and the two registries, and
the type in the vector test's name maps.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar, Self

PROTOCOL = 1
"""Bumped on any message change. A Rig must report exactly this."""

MAX_LABEL = 64
"""The longest Label or Holder text, in bytes."""

MAX_LAST_PANIC = 64
"""The longest `last_panic` text, in bytes."""

FEATURE_WIFI = 1 << 0
"""`Hello` `features` bit: the firmware was built with the `wifi` feature."""

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
    AcquireLease = 0x08
    RenewLease = 0x09
    ReleaseLease = 0x0A


class ErrorCode(IntEnum):
    """A non-zero response `status`. Rigs may send codes not listed here."""

    UnknownRequest = 1
    UnsupportedVersion = 2
    Malformed = 3
    LeaseRequired = 4
    LeaseHeld = 5
    LeaseLost = 6
    Busy = 7
    HardwareFault = 8
    StorageFault = 9
    Internal = 10


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
    features: int
    channel_count: int
    board_revision: str
    hardware_id: bytes
    label: str

    def encode(self, w: _Writer) -> None:
        w.u16(self.protocol)
        w.text(self.firmware_version)
        w.bool(self.dirty)
        w.u8(self.features)
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
            features=r.u8(),
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

    token: int
    mask: int
    values: int

    def encode(self, w: _Writer) -> None:
        w.u64(self.token)
        w.u16(self.mask)
        w.u16(self.values)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(token=r.u64(), mask=r.u16(), values=r.u16())


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

    token: int

    def encode(self, w: _Writer) -> None:
        w.u64(self.token)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(token=r.u64())


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
    TYPE: ClassVar[RequestType] = RequestType.GetStatus

    uptime_ms: int
    reset_reason: int
    """The raw ESP32-S3 `SocResetReason`, or 0 if unknown."""
    last_panic: str
    """Empty = no panic."""
    holder: str
    """Empty = no Holder."""
    crc_failures: int
    oversized_frames: int
    malformed_frames: int
    dropped_logs: int
    expander_faults: int
    usb_tx_dropped: int

    def encode(self, w: _Writer) -> None:
        w.u64(self.uptime_ms)
        w.u8(self.reset_reason)
        w.text(self.last_panic, MAX_LAST_PANIC)
        w.text(self.holder, MAX_LABEL)
        w.u32(self.crc_failures)
        w.u32(self.oversized_frames)
        w.u32(self.malformed_frames)
        w.u32(self.dropped_logs)
        w.u32(self.expander_faults)
        w.u32(self.usb_tx_dropped)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(
            uptime_ms=r.u64(),
            reset_reason=r.u8(),
            last_panic=r.text(MAX_LAST_PANIC),
            holder=r.text(MAX_LABEL),
            crc_failures=r.u32(),
            oversized_frames=r.u32(),
            malformed_frames=r.u32(),
            dropped_logs=r.u32(),
            expander_faults=r.u32(),
            usb_tx_dropped=r.u32(),
        )


# --- Lease -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AcquireLease:
    TYPE: ClassVar[RequestType] = RequestType.AcquireLease

    token: int
    takeover: bool
    holder: str

    def encode(self, w: _Writer) -> None:
        w.u64(self.token)
        w.bool(self.takeover)
        w.text(self.holder, MAX_LABEL)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(token=r.u64(), takeover=r.bool(), holder=r.text(MAX_LABEL))


@dataclass(frozen=True)
class AcquireLeaseReply:
    TYPE: ClassVar[RequestType] = RequestType.AcquireLease

    ttl_ms: int

    def encode(self, w: _Writer) -> None:
        w.u32(self.ttl_ms)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(ttl_ms=r.u32())


@dataclass(frozen=True)
class RenewLease:
    TYPE: ClassVar[RequestType] = RequestType.RenewLease

    token: int
    holder: str

    def encode(self, w: _Writer) -> None:
        w.u64(self.token)
        w.text(self.holder, MAX_LABEL)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(token=r.u64(), holder=r.text(MAX_LABEL))


@dataclass(frozen=True)
class RenewLeaseReply:
    TYPE: ClassVar[RequestType] = RequestType.RenewLease

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


@dataclass(frozen=True)
class ReleaseLease:
    TYPE: ClassVar[RequestType] = RequestType.ReleaseLease

    token: int

    def encode(self, w: _Writer) -> None:
        w.u64(self.token)

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls(token=r.u64())


@dataclass(frozen=True)
class ReleaseLeaseReply:
    TYPE: ClassVar[RequestType] = RequestType.ReleaseLease

    def encode(self, w: _Writer) -> None:
        pass

    @classmethod
    def decode(cls, r: _Reader) -> Self:
        return cls()


# --- Envelope ----------------------------------------------------------------------------------

RequestBody = (
    Hello
    | GetChannels
    | WriteChannels
    | Clear
    | GetStatus
    | AcquireLease
    | RenewLease
    | ReleaseLease
)
ReplyBody = (
    HelloReply
    | GetChannelsReply
    | WriteChannelsReply
    | ClearReply
    | GetStatusReply
    | AcquireLeaseReply
    | RenewLeaseReply
    | ReleaseLeaseReply
)

_REQUESTS: dict[int, type[RequestBody]] = {
    cls.TYPE: cls
    for cls in (
        Hello,
        GetChannels,
        WriteChannels,
        Clear,
        GetStatus,
        AcquireLease,
        RenewLease,
        ReleaseLease,
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
        AcquireLeaseReply,
        RenewLeaseReply,
        ReleaseLeaseReply,
    )
}


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


Message = Request | OkResponse | ErrorResponse | UnknownEvent


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
        case UnknownEvent(type_, body):
            w.u8(type_)
            w.raw(body)
    return w.getvalue()


def decode(payload: bytes) -> Message:
    """Decodes one payload. Raises `DecodeError` if it breaks its byte table."""
    r = _Reader(payload)
    type_ = r.u8()
    if _FIRST_EVENT_TYPE <= type_ < _RESPONSE_BIT:
        return UnknownEvent(type_, payload[1:])
    request_id = r.u32()
    message: Message
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
