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

PROTOCOL = 1
"""Bumped on any message change. A Rig must report exactly this."""

MAX_LABEL = 64
"""The longest Label or Holder text, in bytes."""

FEATURE_WIFI = 1 << 0
"""`Hello` `features` bit: the firmware was built with the `wifi` feature."""

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
    SetLogLevel = 0x07


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


# --- SetLogLevel and the Log Event ------------------------------------------------------------


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


# --- Envelope ----------------------------------------------------------------------------------

RequestBody = Hello | SetLogLevel
ReplyBody = HelloReply | SetLogLevelReply

_REQUESTS: dict[int, type[RequestBody]] = {cls.TYPE: cls for cls in (Hello, SetLogLevel)}
_REPLIES: dict[int, type[ReplyBody]] = {cls.TYPE: cls for cls in (HelloReply, SetLogLevelReply)}
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
