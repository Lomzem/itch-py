"""The Rigs this process has connected, by the endpoint each is reached at: a USB port or a
TCP address.

Connecting to an endpoint again first disconnects the older Rig there, so a notebook cell
that connects can run again. At exit, every Rig still connected is disconnected, releasing its
Lock. Only weak references to Rigs are kept, so a Rig dropped without disconnecting isn't kept
alive: its connection stays open, with any Lock it holds, until then.
"""

from __future__ import annotations

import atexit
import contextlib
import dataclasses
import logging
import os
import socket
import sys
import threading
import weakref
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from itch._connection import Connection  # It imports this module.


class Connected(Protocol):
    """A connected Rig, as the registry sees it."""

    def _replaced(self) -> None:
        """Disconnects, because this process connected to the same Rig again."""
        ...


class Disconnecting(Protocol):
    """What a Rig needs to disconnect, kept apart from the Rig so the registry can disconnect it
    once the script has dropped the Rig."""

    @property
    def connection(self) -> Connection: ...

    def disconnect(self) -> None:
        """Releases the Rig's Lock, if held, and closes its connection."""
        ...


@dataclasses.dataclass(frozen=True)
class _Entry:
    rig: weakref.ref[Connected]
    parts: Disconnecting

    def disconnect(self, *, replaced: bool) -> None:
        """Disconnects the Rig, through the Rig if the script still has it, so that it can say
        it was `replaced`."""
        if (rig := self.rig()) is not None and replaced:
            rig._replaced()  # pyright: ignore[reportPrivateUsage]  # Not part of Rig's API.
        else:
            self.parts.disconnect()


_LOGGER = logging.getLogger("itch")

_connected: dict[str, _Entry] = {}

_registering = threading.Lock()
"""Held while `_connected` changes, never while a Rig disconnects, which may wait for a log
handler that connects."""


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


def held(endpoint: str) -> Connection | None:
    """The open connection this process has at `endpoint`, if any, even if the script has
    dropped its Rig."""
    with _registering:
        entry = _connected.get(endpoint)
    return None if entry is None else entry.parts.connection


def release(*endpoints: str) -> None:
    """Disconnects the Rigs this process has connected at `endpoints`, before connecting to one
    of them again."""
    for endpoint in endpoints:
        with _registering:
            entry = _connected.pop(endpoint, None)
        if entry is not None:
            entry.disconnect(replaced=True)


def claim(endpoint: str, rig: Connected, parts: Disconnecting) -> None:
    """Records `rig` as connected at `endpoint`, disconnecting any older Rig there.

    `parts` disconnects `rig`, and mustn't refer to it, so the script can drop it.
    """
    with _registering:
        older = _connected.get(endpoint)
        _connected[endpoint] = _Entry(weakref.ref(rig), parts)
    if older is not None:
        older.disconnect(replaced=True)


def forget(endpoint: str, rig: Connected) -> None:
    """Forgets `rig`, which has disconnected."""
    with _registering:
        if (entry := _connected.get(endpoint)) is not None and entry.rig() is rig:
            del _connected[endpoint]


@atexit.register
def _disconnect_all() -> None:
    """Disconnects every Rig still connected as the interpreter exits, normally or after an
    uncaught exception, releasing their Locks, whether or not the script still refers to them.
    A killed process can't, and its Holder picks the Lock back up on reconnecting (ADR 0009).

    Registered after `logging`'s own exit hook, so it runs first and its warnings are logged.
    """
    with _registering:
        entries = list(_connected.items())
    for endpoint, entry in entries:
        try:
            entry.disconnect(replaced=False)  # Only logs if releasing fails.
        except Exception:  # Keep going, so one Rig's bug doesn't leave the rest Locked.
            with contextlib.suppress(Exception):  # Even if logging is what failed.
                _LOGGER.exception("Couldn't disconnect the Rig at %s at exit", endpoint)
