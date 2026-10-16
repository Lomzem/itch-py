from __future__ import annotations

import itertools
import time
import warnings
from types import TracebackType
from typing import Self, TypeVar

from itch import _wire
from itch._errors import DevelopmentBuildWarning, ItchError, ProtocolMismatchError
from itch._transport import Disconnected, Transport, open_transport

REQUEST_TIMEOUT = 2.0
"""Seconds to wait for each reply."""

_Reply = TypeVar("_Reply", bound=_wire.ReplyBody)


class Rig:
    """A connected Rig. Get one with `Rig.connect()`, and close it when done.

    ```python
    with Rig.connect("tcp://127.0.0.1:4000") as rig:
        print(rig.label, rig.hardware_id, rig.firmware_version)
    ```
    """

    def __init__(self, transport: Transport) -> None:
        """Takes over an open transport and sends `Hello`. Use `Rig.connect()` instead."""
        self._transport = transport
        self._name = transport.name
        self._request_ids = itertools.count(1)
        try:
            hello = self._request(_wire.Hello(), _wire.HelloReply)
            if hello.protocol != _wire.PROTOCOL:
                raise ProtocolMismatchError(self._name, hello.protocol, _wire.PROTOCOL)
        except BaseException:
            transport.close()
            raise
        self._hello = hello
        self._name = self._label = hello.label

    @classmethod
    def connect(cls, name: str | None = None) -> Self:
        """Connects to a Rig and checks it speaks this itch-py's protocol.

        `name` is `tcp://host:port` for `itch-sim` or a dev-build Rig.
        Warns with `DevelopmentBuildWarning` if the Rig runs a development build.
        """
        rig = cls(open_transport(name))
        if rig._dev_build_notes:
            warnings.warn(
                f"Rig {rig.label} runs a development build ({', '.join(rig._dev_build_notes)}). "
                "Have the dev flash a release build before QA use it.",
                DevelopmentBuildWarning,
                stacklevel=2,
            )
        return rig

    @property
    def label(self) -> str:
        """The Rig's Label, such as `itch-C02718`."""
        return self._label

    @property
    def hardware_id(self) -> str:
        """The Rig's Hardware ID, such as `60:55:F9:C0:27:18`."""
        return ":".join(f"{byte:02X}" for byte in self._hello.hardware_id)

    @property
    def firmware_version(self) -> str:
        """The Rig's firmware version, such as `1.0.0`."""
        return self._hello.firmware_version

    def close(self) -> None:
        """Closes the connection, freeing the Rig for the next script. Safe to call twice."""
        self._transport.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Rig {self.label} {self.hardware_id} firmware {self.firmware_version}>"

    @property
    def _dev_build_notes(self) -> list[str]:
        notes: list[str] = []
        if self._hello.features & _wire.FEATURE_WIFI:
            notes.append("WiFi enabled")
        if self._hello.dirty:
            notes.append("built from uncommitted code")
        return notes

    def _request(self, body: _wire.RequestBody, reply: type[_Reply]) -> _Reply:
        """Sends one request and waits for its reply."""
        request_id = next(self._request_ids) & 0xFFFF_FFFF
        try:
            self._transport.send(_wire.encode(_wire.Request(request_id, body)))
            deadline = time.monotonic() + REQUEST_TIMEOUT
            while (remaining := deadline - time.monotonic()) > 0:
                payload = self._transport.receive(remaining)
                if payload is None:
                    break
                message = _wire.decode(payload)
                if isinstance(message, _wire.Request) or message.request_id != request_id:
                    continue  # Not a reply, or a reply to an earlier request.
                if isinstance(message, _wire.ErrorResponse):
                    raise ItchError(f"Rig {self._name} refused {body.TYPE.name}: {message.detail}")
                if not isinstance(message.body, reply):
                    raise _wire.DecodeError(f"{type(message.body).__name__} answers {body}")
                return message.body
        except Disconnected as err:
            raise ItchError("Rig disconnected; run the script again.") from err
        except _wire.DecodeError as err:
            raise ItchError(f"Rig {self._name} sent a malformed reply: {err}") from err
        raise ItchError(f"Rig {self._name} isn't responding.")
