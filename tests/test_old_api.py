"""Check that the old names still work until ticket 07 removes them.

Ticket 07 replaces this file with tests that the old names fail pointing to their replacements.
"""

import pytest
from acme_widget import AcmeWidget
from conftest import RunningSim
from scripted_rig import channel_writes, granting_writes

from itch import BatchConflictError, DisconnectedError, Rig


def test_old_channel_names_still_drive_and_read_channels(rig: Rig) -> None:
    rig.clear_all()
    rig.set_channel(3, "on")
    assert rig.get_all() == 0x0004
    rig.set_channels({1: "on", 3: "off"})
    assert rig.get_channel(1) == "on"
    assert rig.get_channels([1, 3]) == {1: "on", 3: "off"}
    assert rig.get_all() == 0x0001


def test_close_disconnects_and_releases_the_lock(own_sim: RunningSim) -> None:
    rig = Rig.connect(own_sim.url, holder="alice")
    try:
        rig.close()
        with pytest.raises(DisconnectedError, match="was disconnected by this script"):
            rig.get_all()
        with Rig.connect(own_sim.url, holder="bob", lock=False) as observer:
            assert observer.status().holder is None
    finally:
        rig.disconnect()


def test_a_profile_constructed_from_a_rig_still_drives_a_field(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url) as rig:
        dut = AcmeWidget(rig)
        dut.mode.set("night", encoding=2)
        assert rig.get_all() == 0x0028


def test_a_batch_is_one_mask_write_when_the_block_ends() -> None:
    with granting_writes() as peer, Rig.connect(peer.url, AcmeWidget) as dut, dut.batch():
        dut.resolution.set("4k")
        dut.mode.set("night", encoding=2)
    assert channel_writes(peer) == [(0b11_1011, 0b10_1011)]


def test_a_conflicting_batch_sends_nothing() -> None:
    with (
        granting_writes() as peer,
        Rig.connect(peer.url, AcmeWidget) as dut,
        pytest.raises(BatchConflictError, match=r'CH4: refresh="60hz".*mode="night"'),
    ):
        batch_refresh_and_mode(dut)
    assert channel_writes(peer) == []


def batch_refresh_and_mode(dut: AcmeWidget) -> None:
    with dut.batch():
        dut.refresh.set("60hz")
        dut.mode.set("night")
