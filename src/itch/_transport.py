"""Transports carry whole payloads to and from one Rig.

TCP reaches `itch-sim` and Rigs on the network, and USB serial (in `_usb`) reaches Rigs plugged
in. Both are byte streams that share TAFP framing through `StreamTransport`.
"""

from __future__ import annotations

import contextlib
import socket
from abc import ABC, abstractmethod
from collections import deque
from typing import Protocol
from urllib.parse import urlsplit

from itch._endpoints import release, tcp_endpoint, tcp_endpoints
from itch._errors import ItchError
from itch._frame import FrameDecoder, encode_frame

CONNECT_TIMEOUT = 5.0

_STOP_BACKSTOP = 1.0
"""Seconds a TCP read waits before checking whether to stop, in case shutting the socket down
doesn't wake it."""

NETWORK_CONNECTIONS = 4
"""How many TCP connections a Rig serves at once, beside USB."""


class Disconnected(Exception):
    """The transport's connection closed or failed."""


class Transport(Protocol):
    name: str
    """How the user reached the Rig, such as `tcp://127.0.0.1:4000`."""
    endpoint: str
    """Where the Rig is reached, the same however the user named it, such as
    `tcp://127.0.0.1:4000` for `tcp://localhost:4000`. This process connects one Rig to each."""

    def send(self, payload: bytes) -> None:
        """Sends one payload. Raises `Disconnected`."""
        ...

    def receive(self) -> bytes:
        """Waits for the next payload. Raises `Disconnected` once the connection ends or once
        `stop()` is called."""
        ...

    def stop(self) -> None:
        """Makes a `receive()` waiting in another thread raise `Disconnected` now. Then call
        `close()`. Safe to call twice."""
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
        self._stopped = False

    def send(self, payload: bytes) -> None:
        self._write(encode_frame(payload))

    def receive(self) -> bytes:
        while not self._payloads:
            if self._stopped:
                raise Disconnected("stopped")
            self._payloads.extend(self._decoder.feed(self._read()))
        return self._payloads.popleft()

    def stop(self) -> None:
        self._stopped = True
        self._wake()

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def _wake(self) -> None:
        """Makes a `_read()` waiting in another thread return now."""

    @abstractmethod
    def _write(self, data: bytes) -> None:
        """Writes all of `data`. Raises `Disconnected`."""

    @abstractmethod
    def _read(self) -> bytes:
        """Waits for bytes and returns them. Returns none if it gives up or is woken.

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
        self.endpoint = tcp_endpoint(self._socket.getpeername())
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._socket.settimeout(_STOP_BACKSTOP)

    def close(self) -> None:
        self._socket.close()

    def _wake(self) -> None:
        with contextlib.suppress(OSError):  # Not connected any more.
            self._socket.shutdown(socket.SHUT_RDWR)  # Ends a waiting `recv()`.

    def _write(self, data: bytes) -> None:
        try:
            self._socket.sendall(data)
        except OSError as err:
            raise Disconnected from err

    def _read(self) -> bytes:
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
    """Opens a `tcp://host:port` name, first disconnecting a Rig this process has connected at
    the address it resolves to."""
    url = urlsplit(name)
    if url.hostname is None or url.port is None or url.path not in ("", "/"):
        raise ValueError(f"{name!r} isn't a tcp://host:port name.")
    release(*tcp_endpoints(url.hostname, url.port))
    return TcpTransport(url.hostname, url.port)
