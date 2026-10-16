"""A scripted TCP peer for the few cases `itch-sim` can't produce.

It isn't a Rig: it answers each request with the messages `answer` returns, maybe none, and
records what it was sent.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterable
from types import TracebackType

from itch._frame import FrameDecoder, encode_frame
from itch._wire import (
    HelloReply,
    Message,
    OkResponse,
    Request,
    SetLogLevel,
    SetLogLevelReply,
    decode,
    encode,
)

ACME_HELLO = HelloReply(
    protocol=1,
    firmware_version="1.0.0",
    dirty=False,
    features=0,
    channel_count=16,
    board_revision="A",
    hardware_id=bytes.fromhex("60 55 f9 c0 27 18"),
    label="bench3",
)


class ScriptedRig:
    def __init__(self, answer: Callable[[Request], Iterable[Message]]) -> None:
        self._answer = answer
        self._listener = socket.create_server(("127.0.0.1", 0))
        host, port = self._listener.getsockname()
        self.url = f"tcp://{host}:{port}"
        self.requests: list[Request] = []
        self.closed = threading.Event()
        """Set once the client closes its connection."""
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> ScriptedRig:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._listener.close()

    def _serve(self) -> None:
        connection, _ = self._listener.accept()
        decoder = FrameDecoder()
        with connection:
            while data := connection.recv(4096):
                for payload in decoder.feed(data):
                    request = decode(payload)
                    assert isinstance(request, Request)
                    self.requests.append(request)
                    for reply in self._answer(request):
                        connection.sendall(encode_frame(encode(reply)))
        self.closed.set()


def answering(hello: HelloReply, *before: Message) -> ScriptedRig:
    """A peer that answers `SetLogLevel` and, to anything else, `hello`.

    It sends `before` ahead of every reply.
    """

    def answer(request: Request) -> list[Message]:
        reply = SetLogLevelReply() if isinstance(request.body, SetLogLevel) else hello
        return [*before, OkResponse(request.request_id, reply)]

    return ScriptedRig(answer)
