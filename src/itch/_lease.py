"""A Session's Lease: acquired, kept alive by a heartbeat thread, and released."""

from __future__ import annotations

import getpass
import secrets
import socket
import sys
import threading
from pathlib import Path

from itch import _wire
from itch._connection import Connection
from itch._errors import ItchError, LeaseLostError


class Lease:
    """A Rig's Lease, held by this client. Get one with `Lease.acquire()`.

    A heartbeat thread renews it every third of its lifetime until `release()`. If the heartbeat
    sees someone else take the Rig, `token()` raises `LeaseLostError` from then on.
    """

    def __init__(self, connection: Connection, token: int, holder: str, interval: float) -> None:
        self._connection = connection
        self._token = token
        self._holder = holder
        self._lost_to: str | None = None
        """Who took the Rig, once the heartbeat has seen it go."""
        self._stopped = threading.Event()
        self._heartbeat = threading.Thread(
            target=self._beat, args=(interval,), name="itch-heartbeat", daemon=True
        )
        self._heartbeat.start()

    @classmethod
    def acquire(cls, connection: Connection, holder: str | None, *, takeover: bool) -> Lease:
        """Takes the Rig's Lease as `holder`, by default `user@host script.py`.

        Raises `ValueError` if `holder` is over 64 bytes of UTF-8, and `LeaseHeldError` if
        someone else holds the Rig and `takeover` is false.
        """
        if holder is None:
            holder = _default_holder()
        elif (size := len(holder.encode())) > _wire.MAX_LABEL:
            raise ValueError(
                f"The holder {holder!r} is {size} bytes, but at most {_wire.MAX_LABEL} bytes fit."
            )
        token = _new_token()
        reply = connection.request(
            _wire.AcquireLease(token, takeover, holder), _wire.AcquireLeaseReply
        )
        return cls(connection, token, holder, reply.ttl_ms / 1000 / 3)

    def token(self) -> int:
        """The token for a write. Raises `LeaseLostError` once the heartbeat has seen it go."""
        if self._lost_to is not None:
            raise LeaseLostError(self._connection.name, self._lost_to)
        return self._token

    def release(self) -> None:
        """Stops the heartbeat, waiting out a renewal in flight, then gives up the Lease.

        Does nothing the second time.
        """
        if self._stopped.is_set():
            return
        self._stopped.set()
        self._heartbeat.join()
        self._connection.request(_wire.ReleaseLease(self._token), _wire.ReleaseLeaseReply)

    def _beat(self, interval: float) -> None:
        while self._lost_to is None and not self._stopped.wait(interval):
            try:
                self._connection.request(
                    _wire.RenewLease(self._token, self._holder), _wire.RenewLeaseReply
                )
            except LeaseLostError as err:
                self._lost_to = err.reason
            except ItchError:
                pass  # A failed renewal shows up again on the script's next call, which reports it.


def _new_token() -> int:
    """A random non-zero Lease token."""
    while not (token := secrets.randbits(64)):
        pass
    return token


def _default_holder() -> str:
    """`user@host script.py`, each part cut short with `…` so the whole fits 64 bytes."""
    try:
        user = getpass.getuser()
    except (OSError, KeyError, ImportError):  # Such as a container UID with no passwd entry.
        user = "unknown"
    user = _fit(user, 16)
    host = _fit(socket.gethostname(), 24)
    script = Path(sys.argv[0]).name if sys.argv else ""
    start = f"{user}@{host} "
    return start + _fit(script or "python", _wire.MAX_LABEL - len(start.encode()))


def _fit(text: str, size: int) -> str:
    """`text`, cut short with `…` on a character boundary to fit `size` bytes of UTF-8."""
    data = text.encode()
    if len(data) <= size:
        return text
    return data[: size - len("…".encode())].decode(errors="ignore") + "…"
