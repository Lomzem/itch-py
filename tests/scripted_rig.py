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
from itch._wire import Message, Request, decode, encode


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
