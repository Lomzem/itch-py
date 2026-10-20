"""TAFP framing: `0x00 | COBS(length u16 + payload + CRC-16/CCITT-FALSE) | 0x00`.

The length and CRC are little-endian, and the CRC covers length + payload. See "Framing" in the
`itch` protocol docs.
"""

import binascii
import struct

MAX_PAYLOAD = 1024
"""The largest payload a frame may carry. Larger frames are dropped, never fragmented."""

_MAX_LOGICAL = 2 + MAX_PAYLOAD + 2


def _crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: `crc_hqx` is the same polynomial, started from 0xFFFF."""
    return binascii.crc_hqx(data, 0xFFFF)


def encode_frame(payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload over {MAX_PAYLOAD} bytes")
    logical = struct.pack("<H", len(payload)) + payload
    logical += struct.pack("<H", _crc16(logical))
    return b"\x00" + _cobs(logical) + b"\x00"


def _cobs(data: bytes) -> bytes:
    out = bytearray()
    block = bytearray()
    ended_full = False
    for byte in data:
        ended_full = False
        if byte == 0:
            out += bytes([len(block) + 1]) + block
            block.clear()
        else:
            block.append(byte)
            if len(block) == 0xFE:
                out += b"\xff" + block
                block.clear()
                ended_full = True
    # Data that ends exactly with a full block needs no extra code byte.
    if not ended_full:
        out += bytes([len(block) + 1]) + block
    return bytes(out)


class FrameDecoder:
    """Turns a byte stream into payloads.

    Every `0x00` ends a frame, so the decoder resyncs after noise or a mid-stream join. Empty
    frames are ignored. Dropped frames are counted in `crc_failures` (bad CRC, truncated COBS or
    a wrong length) and `oversized_frames`.
    """

    def __init__(self) -> None:
        self.crc_failures = 0
        self.oversized_frames = 0
        self._buf = bytearray()
        self._started = False
        self._oversized = False
        self._block_left = 0
        self._zero_pending = False

    def feed(self, data: bytes) -> list[bytes]:
        """Feeds bytes and returns the payloads of the frames they complete."""
        payloads: list[bytes] = []
        for byte in data:
            if byte == 0:
                if (payload := self._end_frame()) is not None:
                    payloads.append(payload)
                continue
            self._started = True
            if self._block_left == 0:
                if self._zero_pending:
                    self._store(0)
                self._block_left = byte - 1
                self._zero_pending = byte != 0xFF
            else:
                self._store(byte)
                self._block_left -= 1
        return payloads

    def _store(self, byte: int) -> None:
        if len(self._buf) == _MAX_LOGICAL:
            self._oversized = True
        else:
            self._buf.append(byte)

    def _end_frame(self) -> bytes | None:
        logical, started, oversized = bytes(self._buf), self._started, self._oversized
        complete = self._block_left == 0
        self._buf.clear()
        self._started = self._oversized = self._zero_pending = False
        self._block_left = 0
        if not started:
            return None
        if oversized:
            self.oversized_frames += 1
            return None
        if not complete or not _is_valid(logical):
            self.crc_failures += 1
            return None
        return logical[2:-2]


def _is_valid(logical: bytes) -> bool:
    if len(logical) < 4:
        return False
    (length,) = struct.unpack_from("<H", logical)
    (crc,) = struct.unpack_from("<H", logical, len(logical) - 2)
    return length == len(logical) - 4 and crc == _crc16(logical[:-2])
