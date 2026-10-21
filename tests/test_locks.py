"""Locks: connecting Locks the Rig under the Holder, closing releases it, and Takeover."""

import logging
import subprocess
import sys

import pytest
from conftest import RunningSim
from scripted_rig import ACME_HELLO, ScriptedRig, after_connecting

from itch import LockedError, Rig
from itch._wire import (
    ErrorCode,
    ErrorResponse,
    Hello,
    Lock,
    Message,
    OkResponse,
    ReleaseLock,
    Request,
    SetLogLevel,
    SetLogLevelReply,
)


def test_a_locked_rig_refuses_another_holder_who_can_still_look(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url, holder="alice") as alice:
        alice.set_channel(1, "on")
        with pytest.raises(LockedError, match="Locked by alice; pass take_over=True"):
            Rig.connect(own_sim.url, holder="bob")
        with Rig.connect(own_sim.url, holder="bob", lock=False) as bob:
            assert bob.get_channel(1) == "on"
            assert bob.status().holder == "alice"
            with pytest.raises(LockedError, match="Locked by alice"):
                bob.set_channel(2, "on")
    with Rig.connect(own_sim.url, holder="bob") as bob:  # Alice's close released it.
        assert bob.status().holder == "bob"


def test_a_takeover_refuses_the_old_holder_whose_close_only_warns(
    own_sim: RunningSim, caplog: pytest.LogCaptureFixture
) -> None:
    alice = Rig.connect(own_sim.url, holder="alice")
    alice.set_channel(1, "on")
    with Rig.connect(own_sim.url, holder="bob", take_over=True) as bob:
        assert bob.status().holder == "bob"
        assert bob.get_channel(1) == "on"
        with pytest.raises(LockedError, match="Locked by bob"):
            alice.set_channel(2, "on")
        with caplog.at_level(logging.WARNING, logger="itch"):
            alice.close()
        assert [r.message for r in caplog.records] == [
            "Rig itch-514D01 was taken over before alice released its Lock."
        ]
        assert bob.status().holder == "bob"


def test_the_same_holder_picks_its_lock_back_up_after_a_crash(own_sim: RunningSim) -> None:
    crash = f"""
import os
from itch import Rig
rig = Rig.connect({own_sim.url!r}, holder="alice")
rig.set_channel(3, "on")
os._exit(0)  # Closes the connection without releasing the Lock.
"""
    subprocess.run([sys.executable, "-c", crash], check=True, timeout=30)
    with Rig.connect(own_sim.url, holder="bob", lock=False) as bob:
        assert bob.status().holder == "alice"
    with Rig.connect(own_sim.url, holder="alice") as alice:
        assert alice.status().holder == "alice"
        assert alice.get_channel(3) == "on"


def test_rig_lock_locks_a_look_only_rig_until_the_block_ends(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url, holder="alice", lock=False) as rig:
        assert rig.status().holder is None
        with rig.lock():
            assert rig.status().holder == "alice"
        assert rig.status().holder is None


def test_rig_lock_inside_a_locked_rig_leaves_it_locked(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url, holder="alice") as rig:
        with rig.lock():
            assert rig.status().holder == "alice"
        assert rig.status().holder == "alice"
    with Rig.connect(own_sim.url, holder="bob", lock=False) as bob:
        assert bob.status().holder is None


def refusing_locks(holder: str) -> ScriptedRig:
    """A peer that connects, then refuses every `Lock` as Locked by `holder`."""

    def answer(request: Request) -> list[Message]:
        match request.body:
            case Hello():
                return [OkResponse(request.request_id, ACME_HELLO)]
            case SetLogLevel():
                return [OkResponse(request.request_id, SetLogLevelReply())]
            case _:
                code = ErrorCode.Locked
                return [ErrorResponse(request.body.TYPE, request.request_id, code, holder)]

    return ScriptedRig(answer)


def test_a_refused_lock_closes_the_connection_without_taking_over() -> None:
    with refusing_locks("alice") as peer:
        with pytest.raises(LockedError, match="Locked by alice"):
            Rig.connect(peer.url, holder="bob")
        assert peer.closed.wait(2)
    assert [r.body for r in peer.requests if isinstance(r.body, Lock | ReleaseLock)] == [
        Lock("bob", takeover=False)
    ]


def test_a_lock_is_released_once_however_often_it_is_released() -> None:
    with after_connecting(lambda request: []) as peer:
        with Rig.connect(peer.url, holder="alice") as rig, rig.lock() as held:
            held.release()
            held.release()
        assert peer.closed.wait(2)
    releases = [r.body for r in peer.requests if isinstance(r.body, ReleaseLock)]
    assert releases == [ReleaseLock("alice")]


def test_closing_after_the_connection_dropped_skips_the_release_quietly(
    own_sim: RunningSim, caplog: pytest.LogCaptureFixture
) -> None:
    rig = Rig.connect(own_sim.url)
    own_sim.stop()
    with caplog.at_level(logging.DEBUG, logger="itch"):
        rig.close()
    assert caplog.records == []
