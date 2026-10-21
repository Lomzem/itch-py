"""The Rigs this process has connected, by the endpoint each is reached at: a USB port or a
TCP address.

Connecting to an endpoint again first disconnects the older Rig there, so a notebook cell
that connects can run again. At exit, every Rig still connected is disconnected, releasing its
Lock. Only weak references are kept, so a Rig dropped without disconnecting isn't kept alive.
"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import sys
import weakref
from typing import Protocol


class Connected(Protocol):
    """A connected Rig, as the registry sees it."""

    @property
    def label(self) -> str: ...

    @property
    def hardware_id(self) -> str: ...

    @property
    def firmware_version(self) -> str: ...

    def disconnect(self) -> None: ...

    def _replaced(self) -> None:
        """Disconnects, because this process connected to the same Rig again."""
        ...


_LOGGER = logging.getLogger("itch")

_connected: weakref.WeakValueDictionary[str, Connected] = weakref.WeakValueDictionary()


def usb_endpoint(device: str) -> str:
    """The endpoint of USB port `device`, the same for every name of the port."""
    if sys.platform == "win32":
        return device.casefold()
    return os.path.realpath(device)  # Such as /dev/serial/by-id/…


def tcp_endpoint(address: tuple[str, int] | tuple[str, int, int, int]) -> str:
    """The endpoint of a socket address, such as `getpeername()` gives."""
    host, port = address[0], address[1]
    return f"tcp://[{host}]:{port}" if ":" in host else f"tcp://{host}:{port}"


def tcp_endpoints(host: str, port: int) -> list[str]:
    """Every endpoint `host:port` resolves to, or none if it doesn't resolve."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return []  # Connecting then fails, saying why.
    return [tcp_endpoint(info[4]) for info in infos]  # pyright: ignore[reportArgumentType]


def held(endpoint: str) -> Connected | None:
    """The Rig this process has connected at `endpoint`, if any."""
    return _connected.get(endpoint)


def release(*endpoints: str) -> None:
    """Disconnects the Rigs this process has connected at `endpoints`, before connecting to one
    of them again."""
    for endpoint in endpoints:
        if (rig := _connected.pop(endpoint, None)) is not None:
            rig._replaced()  # pyright: ignore[reportPrivateUsage]  # Not part of Rig's API.


def claim(endpoint: str, rig: Connected) -> None:
    """Records `rig` as connected at `endpoint`, disconnecting any older Rig there."""
    release(endpoint)
    _connected[endpoint] = rig


def forget(endpoint: str, rig: Connected) -> None:
    """Forgets `rig`, which has disconnected."""
    if _connected.get(endpoint) is rig:
        del _connected[endpoint]


@atexit.register
def _disconnect_all() -> None:
    """Disconnects every Rig still connected as the interpreter exits, normally or after an
    uncaught exception, releasing their Locks. A killed process can't, and its Holder picks the
    Lock back up on reconnecting (ADR 0009)."""
    for rig in list(_connected.values()):
        try:
            rig.disconnect()  # It forgets itself, and only logs if releasing fails.
        except Exception:  # Keep going, so one Rig's bug doesn't leave the rest Locked.
            _LOGGER.exception("Couldn't disconnect Rig %s at exit", rig.label)
