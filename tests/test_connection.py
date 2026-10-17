"""Connection behaviour: a silent Rig is retried once, and a dropped connection isn't reopened."""

import pytest
from conftest import RunningSim
from scripted_rig import ACME_HELLO, ScriptedRig

from itch import DisconnectedError, NotRespondingError, Rig, _rig
from itch._wire import (
    GetChannels,
    GetChannelsReply,
    Hello,
    Message,
    OkResponse,
    Request,
)


@pytest.fixture(autouse=True)
def short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_rig, "REQUEST_TIMEOUT", 0.2)


def answering_after(silences: int) -> ScriptedRig:
    """A peer that answers `Hello`, then ignores the first `silences` other requests."""
    ignored = 0

    def answer(request: Request) -> list[Message]:
        nonlocal ignored
        if isinstance(request.body, Hello):
            return [OkResponse(request.request_id, ACME_HELLO)]
        if ignored < silences:
            ignored += 1
            return []
        return [OkResponse(request.request_id, GetChannelsReply(0x0001))]

    return ScriptedRig(answer)


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
