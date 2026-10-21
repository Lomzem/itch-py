"""One DUT object drives Fields and Channels, with Rig administration on `dut.rig`."""

from collections.abc import Callable
from contextlib import nullcontext
from typing import cast

import pytest
from acme_widget import AcmeWidget
from conftest import RunningSim
from scripted_rig import after_connecting, channel_writes, granting_writes

from itch import ChannelState, DisconnectedError, Profile, Rig
from itch._wire import Clear, ReleaseLock, WriteChannels


@pytest.mark.parametrize("keyword", [False, True], ids=["positional", "keyword"])
def test_connect_with_a_profile_drives_fields_and_channels(sim: str, keyword: bool) -> None:
    dut = Rig.connect(sim, profile=AcmeWidget) if keyword else Rig.connect(sim, AcmeWidget)
    try:
        assert isinstance(dut, AcmeWidget)
        assert isinstance(dut.rig, Rig)
        dut.clear_all()
        dut.resolution.set("1080p")
        dut.set(16)
        state = dut.get_all()
        assert isinstance(state, ChannelState)
        assert state == 0x8002
        assert dut.rig.get_all() == 0x8002
        assert dut.get(16) is True
        assert dut.resolution.get() == "1080p"
        dut.clear(16)
        assert dut.get(16) is False
        assert dut.get_all() == 0x0002
        assert dut.resolution.get() == "1080p"
    finally:
        dut.rig.close()


@pytest.mark.parametrize("lock", [True, False], ids=["locked", "unlocked"])
def test_profile_connect_preserves_holder_and_lock_options(own_sim: RunningSim, lock: bool) -> None:
    dut = Rig.connect(own_sim.url, AcmeWidget, holder="alice", lock=lock)
    try:
        assert dut.rig.holder == "alice"
        assert dut.rig.status().holder == ("alice" if lock else None)
        dut.set(3)
        assert dut.get(3) is True
    finally:
        dut.rig.close()


@pytest.mark.parametrize(
    ("verb", "args", "kwargs", "expected"),
    [
        pytest.param("write", (), {"set": [1, 5], "clear": [3]}, (0x0015, 0x0011), id="write"),
        pytest.param("apply", (0x6742,), {"mask": 0xFF00}, (0xFF00, 0x6700), id="apply-masked"),
        pytest.param("set_all", (), {}, (0xFFFF, 0xFFFF), id="set-all"),
    ],
)
def test_dut_channel_verbs_send_one_exact_mask_write(
    verb: str,
    args: tuple[int, ...],
    kwargs: dict[str, list[int] | int],
    expected: tuple[int, int],
) -> None:
    with granting_writes() as peer:
        dut = Rig.connect(peer.url, AcmeWidget)
        try:
            getattr(dut, verb)(*args, **kwargs)
        finally:
            dut.rig.close()
    assert channel_writes(peer) == [expected]
    assert not any(isinstance(request.body, Clear) for request in peer.requests)


def test_dut_rejects_a_contradictory_write_without_sending() -> None:
    with granting_writes() as peer:
        dut = Rig.connect(peer.url, AcmeWidget)
        try:
            with pytest.raises(ValueError, match="both set and clear"):
                dut.write(set=[1, 5], clear=[3, 5])
        finally:
            dut.rig.close()
    assert not any(isinstance(request.body, WriteChannels | Clear) for request in peer.requests)


def test_rig_administration_is_only_available_through_dut_rig(sim: str) -> None:
    dut = Rig.connect(sim, AcmeWidget)
    try:
        for name in (
            "label",
            "hardware_id",
            "firmware_version",
            "holder",
            "lock",
            "status",
            "set_label",
            "set_wifi",
            "clear_wifi",
            "set_address",
            "use_dhcp",
        ):
            assert not hasattr(dut, name), name
            assert hasattr(dut.rig, name), name
    finally:
        dut.rig.close()


@pytest.mark.parametrize("profile", [Rig, object(), Profile], ids=["Rig", "instance", "Profile"])
def test_connect_rejects_non_profile_subclasses_before_connecting(profile: object) -> None:
    # This address cannot connect: validation must raise TypeError before opening it.
    connect = cast(Callable[..., object], Rig.connect)
    with pytest.raises(TypeError, match="Profile subclass"):
        connect("tcp://127.0.0.1:0", profile=profile)


@pytest.mark.parametrize("profiled", [False, True], ids=["Rig", "DUT"])
def test_disconnect_releases_the_lock_without_changing_channels(
    own_sim: RunningSim, profiled: bool
) -> None:
    client = (
        Rig.connect(own_sim.url, AcmeWidget, holder="alice")
        if profiled
        else Rig.connect(own_sim.url, holder="alice")
    )
    rig = client.rig if isinstance(client, Profile) else client
    try:
        client.set(1, 5, 16)
        client.disconnect()
        with Rig.connect(own_sim.url, holder="bob") as bob:
            assert bob.status().holder == "bob"
            assert bob.get_all() == 0x8011
    finally:
        rig.close()


@pytest.mark.parametrize("profiled", [False, True], ids=["Rig", "DUT"])
def test_disconnect_is_idempotent_and_later_use_sends_nothing(profiled: bool) -> None:
    with after_connecting(lambda request: []) as peer:
        client = (
            Rig.connect(peer.url, AcmeWidget, holder="alice")
            if profiled
            else Rig.connect(peer.url, holder="alice")
        )
        rig = client.rig if isinstance(client, Profile) else client
        connected_requests = len(peer.requests)
        try:
            client.disconnect()
            client.disconnect()
            assert peer.closed.wait(2)
            with pytest.raises(DisconnectedError, match="was disconnected by this script"):
                client.set(1)
            with pytest.raises(DisconnectedError, match="was disconnected by this script"):
                client.get_all()
            if isinstance(client, AcmeWidget):
                with pytest.raises(DisconnectedError, match="was disconnected by this script"):
                    client.resolution.set("1080p")
                with pytest.raises(DisconnectedError, match="was disconnected by this script"):
                    client.rig.get_all()
        finally:
            rig.close()
    assert [request.body for request in peer.requests[connected_requests:]] == [
        ReleaseLock("alice")
    ]


@pytest.mark.parametrize("profiled", [False, True], ids=["Rig", "DUT"])
@pytest.mark.parametrize("raises", [False, True], ids=["normal-exit", "exception-exit"])
def test_context_exit_disconnects_without_changing_channels(
    own_sim: RunningSim, profiled: bool, raises: bool
) -> None:
    client = (
        Rig.connect(own_sim.url, AcmeWidget, holder="alice")
        if profiled
        else Rig.connect(own_sim.url, holder="alice")
    )
    rig = client.rig if isinstance(client, Profile) else client
    sentinel = RuntimeError("the script failed inside the with block")
    try:
        with (
            pytest.raises(RuntimeError) if raises else nullcontext() as caught,
            client as entered,
        ):
            assert entered is client
            entered.set(1, 5, 16)
            if raises:
                raise sentinel
        if raises:
            assert caught is not None
            assert caught.value is sentinel
        with pytest.raises(DisconnectedError, match="was disconnected by this script"):
            client.get_all()
        with Rig.connect(own_sim.url, holder="bob") as bob:
            assert bob.status().holder == "bob"
            assert bob.get_all() == 0x8011
    finally:
        rig.close()
