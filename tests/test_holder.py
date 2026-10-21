"""The Holder: who a script is, sent with every change it makes."""

import getpass
import socket

import pytest
from conftest import RunningSim
from scripted_rig import ScriptedRig, after_connecting

from itch import ItchError, Rig
from itch._wire import (
    Clear,
    ClearReply,
    OkResponse,
    ReplyBody,
    RequestBody,
    SetLabel,
    SetLabelReply,
    WriteChannels,
    WriteChannelsReply,
)


def taking_changes() -> ScriptedRig:
    """A peer that accepts every Channel write, Clear and rename."""
    replies: dict[type[RequestBody], ReplyBody] = {
        WriteChannels: WriteChannelsReply(0),
        Clear: ClearReply(0),
        SetLabel: SetLabelReply("bench4"),
    }
    return after_connecting(
        lambda request: [OkResponse(request.request_id, replies[type(request.body)])]
    )


def holders_sent(peer: ScriptedRig) -> list[str]:
    """The Holder of every change `peer` was sent, oldest first."""
    return [
        r.body.holder for r in peer.requests if isinstance(r.body, WriteChannels | Clear | SetLabel)
    ]


def test_every_change_carries_the_holder() -> None:
    with taking_changes() as peer, Rig.connect(peer.url, holder="qa@bench-pc") as rig:
        assert rig.holder == "qa@bench-pc"
        rig.set(1)
        rig.clear_all()
        rig.set_label("bench4")
    assert holders_sent(peer) == ["qa@bench-pc"] * 3


@pytest.mark.parametrize(
    ("user", "host", "holder"),
    [
        ("qa", "bench-pc", "qa@bench-pc"),
        ("q" * 20, "h" * 50, "q" * 20 + "@" + "h" * 43),
        ("qa", "ü" * 40, "qa@" + "ü" * 30),
    ],
    ids=["plain", "long", "cut-at-a-character"],
)
def test_the_default_holder_is_user_at_host_cut_to_64_bytes(
    monkeypatch: pytest.MonkeyPatch, user: str, host: str, holder: str
) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: user)
    monkeypatch.setattr(socket, "gethostname", lambda: host)
    with taking_changes() as peer, Rig.connect(peer.url) as rig:
        rig.clear_all()
    assert holders_sent(peer) == [holder]


@pytest.mark.parametrize("error", [OSError, KeyError, ImportError])
def test_an_unreadable_user_name_asks_for_a_holder(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    def getuser() -> str:
        raise error("No username set in the environment")

    monkeypatch.setattr(getpass, "getuser", getuser)
    with pytest.raises(ItchError, match=r"pass Rig\.connect\(\) a holder"):
        Rig.connect("tcp://127.0.0.1:1")


@pytest.mark.parametrize("holder", ["", "ü" * 33], ids=["empty", "65-bytes"])
def test_a_holder_empty_or_over_64_bytes_is_a_value_error(holder: str) -> None:
    with pytest.raises(ValueError, match="must be 1 to 64"):
        Rig.connect("tcp://127.0.0.1:1", holder=holder)


def test_changes_carrying_a_holder_succeed_on_an_unlocked_rig(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url, holder="qa@bench-pc", lock=False) as rig:
        rig.set(1, 2)
        rig.clear_all()
        rig.set(3)
        rig.set_label("bench4")
        assert rig.get_all() == 0x0004
        assert rig.label == "bench4"
        assert rig.status().holder is None
