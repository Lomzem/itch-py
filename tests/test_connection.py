"""Connection behaviour: a silent Rig is retried once, and a dropped connection isn't reopened."""

import pytest
from conftest import RunningSim
from scripted_rig import ScriptedRig, after_connecting

from itch import DisconnectedError, ItchError, NotRespondingError, Rig, _connection
from itch._wire import (
    ClearReply,
    GetChannels,
    GetChannelsReply,
    Message,
    OkResponse,
    Request,
)


@pytest.fixture(autouse=True)
def short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_connection, "REQUEST_TIMEOUT", 0.2)


def answering_after(silences: int) -> ScriptedRig:
    """A peer that connects, then ignores the first `silences` requests."""
    ignored = 0

    def answer(request: Request) -> list[Message]:
        nonlocal ignored
        if ignored < silences:
            ignored += 1
            return []
        return [OkResponse(request.request_id, GetChannelsReply(0x0001))]

    return after_connecting(answer)


def sent_get_channels(peer: ScriptedRig) -> list[Request]:
    return [request for request in peer.requests if isinstance(request.body, GetChannels)]


def test_a_silent_rig_is_retried_once_with_a_fresh_request_id() -> None:
    with answering_after(1) as peer, Rig.connect(peer.url) as rig:
        assert rig.get_channel(1) == "on"
    first, retry = sent_get_channels(peer)
    assert first.request_id != retry.request_id


def test_a_rig_silent_after_the_retry_isnt_responding() -> None:
    with (
        answering_after(2) as peer,
        Rig.connect(peer.url) as rig,
        pytest.raises(NotRespondingError) as raised,
    ):
        rig.get_channels()
    assert str(raised.value) == "Rig bench3 isn't responding."
    assert len(sent_get_channels(peer)) == 2


def test_a_dropped_connection_fails_every_later_call_without_reconnecting(
    own_sim: RunningSim,
) -> None:
    with Rig.connect(own_sim.url) as rig:
        own_sim.stop()
        for _ in range(2):
            with pytest.raises(DisconnectedError) as raised:
                rig.get_channels()
            assert str(raised.value) == "Rig disconnected; run the script again."


def test_a_reply_of_the_wrong_kind_is_malformed() -> None:
    def answer(request: Request) -> list[Message]:
        return [OkResponse(request.request_id, ClearReply(0))]

    with (
        after_connecting(answer) as peer,
        Rig.connect(peer.url) as rig,
        pytest.raises(
            ItchError,
            match=r"^Rig bench3 sent a malformed reply: ClearReply answers GetChannels$",
        ),
    ):
        rig.get_channels()
