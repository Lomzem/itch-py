"""The Rigs this process has connected, by the endpoint each is reached at: a USB port or a
TCP address.

Connecting to an endpoint again first disconnects the older Rig there, so a notebook cell
that connects can run again. At exit, every Rig still connected is disconnected, releasing its
Lock. Only weak references to Rigs are kept, so a Rig dropped without disconnecting isn't kept
alive; its connection, which stays open, is what is disconnected.
"""

from __future__ import annotations

import atexit
import dataclasses
import logging
import os
import socket
import sys
import weakref
from collections.abc import Callable
from typing import Protocol


class Connected(Protocol):
    """A connected Rig, as the registry sees it."""

    @property
    def label(self) -> str: ...

    @property
    def hardware_id(self) -> str: ...

    @property
    def firmware_version(self) -> str: ...

    def _replaced(self) -> None:
        """Disconnects, because this process connected to the same Rig again."""
        ...

    def _refresh(self) -> None:
        """Asks the Rig its Label again, since another connection may have renamed it."""
        ...


@dataclasses.dataclass(frozen=True)
class _Entry:
    rig: weakref.ref[Connected]
    disconnect: Callable[[], None]
    """Releases the Rig's Lock and closes its connection, without referring to the Rig, which
    the script may have dropped."""


_LOGGER = logging.getLogger("itch")

_connected: dict[str, _Entry] = {}


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
    """The Rig this process has connected at `endpoint`, if any. One the script has dropped is
    disconnected first, freeing the endpoint, since nothing else could use it."""
    if (entry := _connected.get(endpoint)) is None:
        return None
    if (rig := entry.rig()) is None:
        del _connected[endpoint]
        entry.disconnect()
    return rig


def release(*endpoints: str) -> None:
    """Disconnects the Rigs this process has connected at `endpoints`, before connecting to one
    of them again."""
    for endpoint in endpoints:
        if (entry := _connected.pop(endpoint, None)) is None:
            continue
        if (rig := entry.rig()) is not None:
            rig._replaced()  # pyright: ignore[reportPrivateUsage]  # Not part of Rig's API.
        else:
            entry.disconnect()


def claim(endpoint: str, rig: Connected, disconnect: Callable[[], None]) -> None:
    """Records `rig` as connected at `endpoint`, disconnecting any older Rig there.

    `disconnect` releases its Lock and closes its connection, and mustn't refer to `rig`.
    """
    release(endpoint)
    _connected[endpoint] = _Entry(weakref.ref(rig), disconnect)


def forget(endpoint: str, rig: Connected) -> None:
    """Forgets `rig`, which has disconnected."""
    if (entry := _connected.get(endpoint)) is not None and entry.rig() is rig:
        del _connected[endpoint]


@atexit.register
def _disconnect_all() -> None:
    """Disconnects every Rig still connected as the interpreter exits, normally or after an
    uncaught exception, releasing their Locks, whether or not the script still refers to them.
    A killed process can't, and its Holder picks the Lock back up on reconnecting (ADR 0009).

    Registered after `logging`'s own exit hook, so it runs first and its warnings are logged.
    """
    for endpoint, entry in list(_connected.items()):
        try:
            entry.disconnect()  # Only logs if releasing fails.
        except Exception:  # Keep going, so one Rig's bug doesn't leave the rest Locked.
            _LOGGER.exception("Couldn't disconnect the Rig at %s at exit", endpoint)
