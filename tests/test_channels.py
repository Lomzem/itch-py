"""Setting and reading Channels against `itch-sim`."""

import re

import pytest

from itch import Rig

ALL_OFF = dict.fromkeys(range(1, 17), "off")


def test_sets_and_reads_one_channel(rig: Rig) -> None:
    rig.clear()
    rig.set_channel(3, "on")
    assert rig.get_channel(3) == "on"
    assert rig.get_channel(4) == "off"
    rig.set_channel(3, "off")
    assert rig.get_channel(3) == "off"


def test_set_channels_changes_only_the_listed_channels(rig: Rig) -> None:
    rig.clear()
    rig.set_channels({1: "on", 2: "on"})
    rig.set_channels({1: "off", 16: "on"})
    assert rig.get_channels() == {**ALL_OFF, 2: "on", 16: "on"}


def test_clear_turns_every_channel_off(rig: Rig) -> None:
    for ch in range(1, 17):
        rig.set_channel(ch, "on")
    assert set(rig.get_channels().values()) == {"on"}
    rig.clear()
    assert rig.get_channels() == ALL_OFF


def test_get_channels_reads_the_listed_channels_in_order(rig: Rig) -> None:
    rig.clear()
    rig.set_channel(16, "on")
    assert list(rig.get_channels([16, 1]).items()) == [(16, "on"), (1, "off")]


def test_channel_calls_take_ch_pos_and_chs_by_name(rig: Rig) -> None:
    rig.clear()
    rig.set_channel(ch=7, pos="on")
    assert rig.get_channel(ch=7) == "on"
    assert rig.get_channels(chs=[7, 8]) == {7: "on", 8: "off"}


def test_channels_survive_closing_and_reconnecting(sim: str) -> None:
    # Closing never Clears: the Rig keeps the Channels for the next script.
    with Rig.connect(sim) as writer:
        writer.clear()
        writer.set_channels({5: "on", 6: "on"})
    with Rig.connect(sim) as reader:
        assert reader.get_channels() == {**ALL_OFF, 5: "on", 6: "on"}


@pytest.mark.parametrize("channel", [0, 17, -1, True, 1.0, "3"])
def test_a_channel_outside_1_to_16_raises_value_error(rig: Rig, channel: int) -> None:
    message = rf"Channel {re.escape(repr(channel))} doesn't exist.*1 to 16"
    with pytest.raises(ValueError, match=message):
        rig.get_channel(channel)
    with pytest.raises(ValueError, match=message):
        rig.get_channels([2, channel])
    with pytest.raises(ValueError, match=message):
        rig.set_channel(channel, "on")
    with pytest.raises(ValueError, match=message):
        rig.set_channels({2: "on", channel: "off"})


def test_an_invalid_position_raises_value_error(rig: Rig) -> None:
    rig.clear()
    with pytest.raises(ValueError, match=r"'of' isn't a Channel position.*\"on\" or \"off\""):
        rig.set_channel(1, "of")  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match="'ON'"):
        rig.set_channels({1: "on", 2: "ON"})  # pyright: ignore[reportArgumentType]
    assert rig.get_channel(1) == "off"
