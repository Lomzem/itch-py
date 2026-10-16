"""Connecting to a Rig over TCP and checking its `Hello`."""

import dataclasses
import re
import socket
import warnings

import pytest
from scripted_rig import ScriptedRig

from itch import DevelopmentBuildWarning, ItchError, ProtocolMismatchError, Rig
from itch._wire import (
    FEATURE_WIFI,
    Hello,
    HelloReply,
    Message,
    OkResponse,
    Request,
    UnknownEvent,
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


def answering(hello: HelloReply, *before: Message) -> ScriptedRig:
    def answer(request: Request) -> list[Message]:
        return [*before, OkResponse(request.request_id, hello)]

    return ScriptedRig(answer)


def test_connects_to_the_simulator(sim: str) -> None:
    with Rig.connect(sim) as rig:
        assert rig.hardware_id == "02:00:00:51:4D:01"
        assert rig.label == "itch-514D01"
        assert re.fullmatch(r"\d+\.\d+\.\d+", rig.firmware_version)


def test_sends_hello_first() -> None:
    with answering(ACME_HELLO) as peer, Rig.connect(peer.url) as rig:
        assert peer.requests[0].body == Hello()
        assert (rig.label, rig.hardware_id) == ("bench3", "60:55:F9:C0:27:18")


def test_ignores_unknown_events_and_stale_replies() -> None:
    stale = OkResponse(0xDEAD, dataclasses.replace(ACME_HELLO, label="stale"))
    with (
        answering(ACME_HELLO, UnknownEvent(0x7F, b"\x01\x02"), stale) as peer,
        Rig.connect(peer.url) as rig,
    ):
        assert rig.label == "bench3"


def test_refuses_a_protocol_mismatch() -> None:
    with answering(dataclasses.replace(ACME_HELLO, protocol=2)) as peer:
        with pytest.raises(ProtocolMismatchError) as raised:
            Rig.connect(peer.url)
        assert peer.closed.wait(2)
    assert isinstance(raised.value, ItchError)
    message = str(raised.value)
    assert "protocol 2" in message, message
    assert "protocol 1" in message, message
    assert "update the Rig or itch-py" in message, message


@pytest.mark.parametrize(
    "hello",
    [
        pytest.param(dataclasses.replace(ACME_HELLO, dirty=True), id="dirty"),
        pytest.param(dataclasses.replace(ACME_HELLO, features=FEATURE_WIFI), id="wifi"),
    ],
)
def test_warns_about_a_development_build(hello: HelloReply) -> None:
    with answering(hello) as peer, pytest.warns(DevelopmentBuildWarning, match="bench3"):
        Rig.connect(peer.url).close()


def test_closes_when_the_warning_is_raised_as_an_error() -> None:
    with answering(dataclasses.replace(ACME_HELLO, dirty=True)) as peer:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(DevelopmentBuildWarning):
                Rig.connect(peer.url)
        assert peer.closed.wait(2)


def test_closes_at_the_end_of_a_with_block() -> None:
    with answering(ACME_HELLO) as peer:
        with Rig.connect(peer.url):
            assert not peer.closed.is_set()
        assert peer.closed.wait(2)


def test_close_is_safe_to_call_twice() -> None:
    with answering(ACME_HELLO) as peer:
        rig = Rig.connect(peer.url)
        rig.close()
        rig.close()
        assert peer.closed.wait(2)


def test_fails_plainly_when_nothing_listens() -> None:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
    with pytest.raises(ItchError, match=f"tcp://127.0.0.1:{port}"):
        Rig.connect(f"tcp://127.0.0.1:{port}")
