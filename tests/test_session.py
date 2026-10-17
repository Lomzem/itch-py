"""Sessions: acquiring, renewing and releasing the Lease."""

import getpass
import socket
import sys
import time
from typing import Any

import pytest
from conftest import RunningSim
from scripted_rig import ACME_HELLO, ScriptedRig

from itch import LeaseHeldError, LeaseLostError, LeaseRequiredError, Rig, Session
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


def test_closing_the_rig_releases_its_session(sim: str) -> None:
    first = Rig.connect(sim)
    first.session()
    first.close()
    with Rig.connect(sim) as second, second.session():
        second.clear()


HOLDER = "qa@bench-pc acme_test.py"


def test_a_session_on_a_rig_someone_else_holds_names_the_holder(sim: str) -> None:
    with Rig.connect(sim) as first, Rig.connect(sim) as second, first.session(holder=HOLDER):
        with pytest.raises(LeaseHeldError) as raised:
            second.session(holder="dev@laptop other.py")
        assert raised.value.holder == HOLDER
        assert "takeover=True" in str(raised.value)
        with pytest.raises(LeaseRequiredError):
            second.set_channel(1, "on")


def test_takeover_takes_the_rig_and_the_old_holders_next_change_raises(sim: str) -> None:
    with Rig.connect(sim) as first, Rig.connect(sim) as second:
        with first.session(holder=HOLDER):
            first.set_channels({1: "on", 2: "off"})
            with second.session(holder="dev@laptop other.py", takeover=True):
                assert second.get_channels([1, 2]) == {1: "on", 2: "off"}
                with pytest.raises(LeaseLostError) as raised:
                    first.set_channel(2, "on")
                assert raised.value.reason == "dev@laptop other.py"
                second.set_channel(2, "on")
        assert second.get_channels([1, 2]) == {1: "on", 2: "on"}


def test_a_lease_lost_seen_by_the_heartbeat_is_raised_on_the_next_call(sim: str) -> None:
    with Rig.connect(sim) as first, Rig.connect(sim) as second:
        with first.session(holder=HOLDER):
            with second.session(holder="dev@laptop other.py", takeover=True):
                time.sleep(10 / 3 + 0.5)  # Until first's heartbeat has renewed once.
            # The Rig is free again, but first's session has lost it all the same.
            with pytest.raises(LeaseLostError) as raised:
                first.clear()
            assert raised.value.reason == "dev@laptop other.py"
            with pytest.raises(LeaseLostError):
                first.set_channel(1, "on")
        with first.session():
            first.clear()


def test_a_lapsed_session_carries_on_when_nobody_else_took_the_rig() -> None:
    with (
        RunningSim("--clock-rate", "1000") as sim,
        Rig.connect(sim.url) as rig,
        rig.session(holder=HOLDER),
    ):
        rig.set_channel(1, "on")
        time.sleep(0.05)  # 50 s on the Rig's clock, between two heartbeats.
        assert rig.status().holder is None
        rig.set_channel(2, "on")
        assert rig.get_channels([1, 2]) == {1: "on", 2: "on"}


@pytest.mark.parametrize(
    ("user", "host", "script", "holder"),
    [
        ("qa", "bench-pc", "/home/qa/tests/acme_test.py", "qa@bench-pc acme_test.py"),
        ("ü" * 10, "bench-pc", "t.py", "üüüüüü…@bench-pc t.py"),
        (
            "u" * 20,
            "h" * 30,
            "s" * 40 + ".py",
            "uuuuuuuuuuuuu…@hhhhhhhhhhhhhhhhhhhhh… sssssssssssssssssss…",
        ),
        ("qa", "bench-pc", "", "qa@bench-pc python"),
    ],
    ids=["plain", "utf-8", "long", "repl"],
)
def test_the_default_holder_is_user_at_host_and_script(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, user: str, host: str, script: str, holder: str
) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: user)
    monkeypatch.setattr(socket, "gethostname", lambda: host)
    monkeypatch.setattr(sys, "argv", [script])
    with rig.session():
        assert rig.status().holder == holder
    assert len(holder.encode()) <= 64


def test_a_holder_over_64_bytes_is_a_value_error(rig: Rig) -> None:
    with pytest.raises(ValueError, match="64 bytes"):
        rig.session(holder="ü" * 33)
    with rig.session(holder="h" * 64):
        assert rig.status().holder == "h" * 64


def test_a_second_session_on_the_same_rig_is_a_runtime_error(rig: Rig) -> None:
    with rig.session():
        with pytest.raises(RuntimeError, match="already"):
            rig.session()
        rig.clear()
    with rig.session():
        rig.clear()
