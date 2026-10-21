"""A scripted TCP peer for the few cases `itch-sim` can't produce.

It isn't a Rig: it answers each request with the messages `answer` returns, maybe none, and
records what it was sent. An answer given as `bytes` is sent as a raw payload, for replies this
itch-py's codec can't encode.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterable
from types import TracebackType

from itch._frame import FrameDecoder, encode_frame
from itch._wire import (
    Hello,
    HelloReply,
    Lock,
    LockReply,
    Message,
    OkResponse,
    ReleaseLock,
    ReleaseLockReply,
    ReplyBody,
    Request,
    SetLogLevel,
    SetLogLevelReply,
    WriteChannels,
    WriteChannelsReply,
    decode,
    encode,
)

ACME_HELLO = HelloReply(
    protocol=3,
    firmware_version="1.0.0",
    dirty=False,
    channel_count=16,
    board_revision="A",
    hardware_id=bytes.fromhex("60 55 f9 c0 27 18"),
    label="bench3",
)
"""The `Hello` reply of a made-up Rig labelled `bench3`."""


class ScriptedRig:
    def __init__(self, answer: Callable[[Request], Iterable[Message | bytes]]) -> None:
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
                        payload = reply if isinstance(reply, bytes) else encode(reply)
                        connection.sendall(encode_frame(payload))
        self.closed.set()


_GRANTED: dict[type[object], ReplyBody] = {
    SetLogLevel: SetLogLevelReply(),
    Lock: LockReply(),
    ReleaseLock: ReleaseLockReply(),
}
"""The replies to the requests every connection sends besides `Hello`."""


def answering(hello: HelloReply, *before: Message) -> ScriptedRig:
    """A peer that answers `SetLogLevel`, `Lock` and `ReleaseLock`, and anything else `hello`.

    It sends `before` ahead of every reply.
    """

    def answer(request: Request) -> list[Message]:
        reply = _GRANTED.get(type(request.body), hello)
        return [*before, OkResponse(request.request_id, reply)]

    return ScriptedRig(answer)


def after_connecting(answer: Callable[[Request], Iterable[Message]]) -> ScriptedRig:
    """A peer that answers `Hello` (as `bench3`), `SetLogLevel`, `Lock` and `ReleaseLock`.

    It answers the rest with `answer`.
    """

    def answer_all(request: Request) -> Iterable[Message]:
        if isinstance(request.body, Hello):
            return [OkResponse(request.request_id, ACME_HELLO)]
        if (granted := _GRANTED.get(type(request.body))) is not None:
            return [OkResponse(request.request_id, granted)]
        return answer(request)

    return ScriptedRig(answer_all)


def granting_writes() -> ScriptedRig:
    """A peer that takes every Channel write, so a test can count them.

    The sim can't show how many writes reached it.
    """
    return after_connecting(lambda request: [OkResponse(request.request_id, WriteChannelsReply(0))])


def channel_writes(peer: ScriptedRig) -> list[tuple[int, int]]:
    """The `(mask, values)` of every Channel write `peer` was sent, oldest first."""
    return [
        (r.body.mask, r.body.values) for r in peer.requests if isinstance(r.body, WriteChannels)
    ]
