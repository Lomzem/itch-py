"""Connecting to a Rig over TCP and checking its `Hello`."""

import dataclasses
import re
import warnings

import pytest
from scripted_rig import ACME_HELLO, ScriptedRig, answering

from itch import DevelopmentBuildWarning, ProtocolMismatchError, Rig
from itch._wire import Hello, OkResponse, Request, UnknownEvent

# `Hello` result bodies from the conformance vectors of earlier protocols (itch v0.1.1 and
# v0.2.0), for the made-up Rig `itch-C02718`. Protocol 1 has one more byte after `dirty`, so it
# doesn't decode as protocol 3.
OLD_HELLO_BODIES = {
    1: "0100 05312e302e30 00 00 10 0141 6055f9c02718 0b697463682d433032373138",
    2: "0200 05312e302e30 00 10 0141 6055f9c02718 0b697463682d433032373138",
}


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


def answering_hello_body(body: str) -> ScriptedRig:
    """A peer that answers `Hello` with the raw result `body`, in hex."""

    def answer(request: Request) -> list[bytes]:
        header = b"\x81" + request.request_id.to_bytes(4, "little") + b"\x00"
        return [header + bytes.fromhex(body)]

    return ScriptedRig(answer)


@pytest.mark.parametrize("theirs", OLD_HELLO_BODIES, ids=lambda theirs: f"protocol-{theirs}")
def test_refuses_a_rig_speaking_an_earlier_protocol(theirs: int) -> None:
    with answering_hello_body(OLD_HELLO_BODIES[theirs]) as peer:
        with pytest.raises(ProtocolMismatchError) as raised:
            Rig.connect(peer.url)
        assert peer.closed.wait(2)
    assert (raised.value.rig_protocol, raised.value.client_protocol) == (theirs, 3)
    assert str(raised.value) == (
        f"Rig {peer.url} speaks protocol {theirs}, but this itch-py speaks protocol 3. "
        "Have the dev update the Rig or itch-py."
    )


def test_warns_about_a_development_build() -> None:
    with (
        answering(dataclasses.replace(ACME_HELLO, dirty=True)) as peer,
        pytest.warns(DevelopmentBuildWarning, match="bench3"),
    ):
        Rig.connect(peer.url).disconnect()


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
