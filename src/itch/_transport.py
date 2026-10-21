"""Transports carry whole payloads to and from one Rig.

TCP reaches `itch-sim` and Rigs on the network, and USB serial (in `_usb`) reaches Rigs plugged
in. Both are byte streams that share TAFP framing through `StreamTransport`.
"""

from __future__ import annotations

import socket
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Protocol
from urllib.parse import urlsplit

from itch._errors import ItchError
from itch._frame import FrameDecoder, encode_frame

CONNECT_TIMEOUT = 5.0

NETWORK_CONNECTIONS = 4
"""How many TCP connections a Rig serves at once, beside USB."""


class Disconnected(Exception):
    """The transport's connection closed or failed."""


class Transport(Protocol):
    name: str
    """How the user reached the Rig, such as `tcp://127.0.0.1:4000`."""

    def send(self, payload: bytes) -> None:
        """Sends one payload. Raises `Disconnected`."""
        ...

    def receive(self, timeout: float) -> bytes | None:
        """Returns the next payload, or `None` after `timeout` seconds. Raises `Disconnected`."""
        ...

    def close(self) -> None:
        """Closes the connection. Safe to call twice."""
        ...


class StreamTransport(ABC):
    """A transport over a byte stream, framed with TAFP."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._decoder = FrameDecoder()
        self._payloads: deque[bytes] = deque()

    def send(self, payload: bytes) -> None:
        self._write(encode_frame(payload))

    def receive(self, timeout: float) -> bytes | None:
        deadline = time.monotonic() + timeout
        while not self._payloads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._payloads.extend(self._decoder.feed(self._read(remaining)))
        return self._payloads.popleft()

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def _write(self, data: bytes) -> None:
        """Writes all of `data`. Raises `Disconnected`."""

    @abstractmethod
    def _read(self, timeout: float) -> bytes:
        """Returns the bytes available within `timeout` seconds, maybe none.

        Raises `Disconnected` when the stream has ended.
        """


class TcpTransport(StreamTransport):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(f"tcp://{host}:{port}")
        try:
            self._socket = socket.create_connection((host, port), CONNECT_TIMEOUT)
        except ConnectionRefusedError as err:
            # A Rig's firmware stops listening while all its connections are open.
            raise ItchError(
                f"Rig at {self.name} refused the connection; it may already have "
                f"{NETWORK_CONNECTIONS} network connections."
            ) from err
        except OSError as err:
            raise ItchError(f"Can't connect to {self.name}: {err}") from err
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def close(self) -> None:
        self._socket.close()

    def _write(self, data: bytes) -> None:
        try:
            self._socket.sendall(data)
        except OSError as err:
            raise Disconnected from err

    def _read(self, timeout: float) -> bytes:
        self._socket.settimeout(timeout)
        try:
            data = self._socket.recv(4096)
        except TimeoutError:
            return b""
        except OSError as err:
            raise Disconnected from err
        if not data:
            raise Disconnected
        return data


def open_tcp(name: str) -> TcpTransport:
    """Opens a `tcp://host:port` name."""
    url = urlsplit(name)
    if url.hostname is None or url.port is None or url.path not in ("", "/"):
        raise ValueError(f"{name!r} isn't a tcp://host:port name.")
    return TcpTransport(url.hostname, url.port)
