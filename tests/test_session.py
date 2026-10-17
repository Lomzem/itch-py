"""Sessions: acquiring, renewing and releasing the Lease."""

import time
from typing import Any

import pytest
from scripted_rig import ACME_HELLO, ScriptedRig

from itch import LeaseRequiredError, Rig, Session
from itch._wire import (
    AcquireLease,
    AcquireLeaseReply,
    GetChannels,
    GetChannelsReply,
    Hello,
    Message,
    OkResponse,
    ReleaseLease,
    ReleaseLeaseReply,
    RenewLease,
    RenewLeaseReply,
    ReplyBody,
    Request,
    RequestBody,
    SetLogLevel,
    SetLogLevelReply,
)


def lease_peer(ttl_ms: int) -> ScriptedRig:
    """A peer granting Leases that live `ttl_ms`, with CH1 on."""
    replies: dict[type[RequestBody], ReplyBody] = {
        Hello: ACME_HELLO,
        SetLogLevel: SetLogLevelReply(),
        AcquireLease: AcquireLeaseReply(ttl_ms),
        RenewLease: RenewLeaseReply(),
        ReleaseLease: ReleaseLeaseReply(),
        GetChannels: GetChannelsReply(0x0001),
    }

    def answer(request: Request) -> list[Message]:
        return [OkResponse(request.request_id, replies[type(request.body)])]

    return ScriptedRig(answer)


def sent(peer: ScriptedRig) -> list[type[Any]]:
    return [type(request.body) for request in peer.requests]


def test_a_session_releases_at_the_end_of_its_with_block(rig: Rig) -> None:
    with rig.session() as session:
        assert isinstance(session, Session)
        rig.set_channel(1, "on")
    with pytest.raises(LeaseRequiredError):
        rig.set_channel(1, "off")
    assert rig.get_channel(1) == "on"


def test_release_is_safe_to_call_twice(rig: Rig) -> None:
    session = rig.session()
    rig.clear()
    session.release()
    session.release()
    with pytest.raises(LeaseRequiredError):
        rig.clear()


def test_the_heartbeat_renews_every_third_of_the_ttl_until_release() -> None:
    with lease_peer(ttl_ms=300) as peer, Rig.connect(peer.url) as rig:
        session = rig.session()
        assert sent(peer) == [Hello, SetLogLevel, AcquireLease]
        time.sleep(0.35)
        session.release()
        time.sleep(0.25)
    acquire, *renewals, release = (request.body for request in peer.requests[2:])
    assert isinstance(acquire, AcquireLease)
    assert acquire.token != 0
    assert 2 <= len(renewals) <= 4, renewals
    assert all(r == RenewLease(acquire.token, acquire.holder) for r in renewals), renewals
    assert release == ReleaseLease(acquire.token)


def test_the_heartbeat_does_not_disturb_user_requests() -> None:
    with lease_peer(ttl_ms=15) as peer, Rig.connect(peer.url) as rig, rig.session():
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            assert rig.get_channel(1) == "on"
        assert RenewLease in sent(peer)


def test_each_session_gets_a_fresh_random_token() -> None:
    with lease_peer(ttl_ms=10_000) as peer, Rig.connect(peer.url) as rig:
        for _ in range(3):
            rig.session().release()
    tokens = {r.body.token for r in peer.requests if isinstance(r.body, AcquireLease)}
    assert len(tokens) == 3
    assert 0 not in tokens


def test_closing_the_rig_releases_its_session() -> None:
    with lease_peer(ttl_ms=10_000) as peer:
        rig = Rig.connect(peer.url)
        rig.session()
        rig.close()
        assert peer.closed.wait(2)
    assert sent(peer)[-1] is ReleaseLease
