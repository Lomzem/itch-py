"""Setting and reading Channels against `itch-sim`."""

import re
from collections.abc import Iterable

import pytest

import itch
from itch import Rig

ALL_OFF = dict.fromkeys(range(1, 17), "off")


def test_sets_and_reads_one_channel(rig: Rig) -> None:
    rig.clear_all()
    rig.set_channel(3, "on")
    assert rig.get_channel(3) == "on"
    assert rig.get_channel(4) == "off"
    rig.set_channel(3, "off")
    assert rig.get_channel(3) == "off"


def test_set_channels_changes_only_the_listed_channels(rig: Rig) -> None:
    rig.clear_all()
    rig.set_channels({1: "on", 2: "on"})
    rig.set_channels({1: "off", 16: "on"})
    assert rig.get_channels() == {**ALL_OFF, 2: "on", 16: "on"}


def test_set_all_and_clear_all_turn_every_channel_on_then_off(rig: Rig) -> None:
    rig.set_all()
    assert set(rig.get_channels().values()) == {"on"}
    rig.clear_all()
    assert rig.get_channels() == ALL_OFF


def test_get_channels_reads_the_listed_channels_in_order(rig: Rig) -> None:
    rig.clear_all()
    rig.set_channel(16, "on")
    assert list(rig.get_channels([16, 1]).items()) == [(16, "on"), (1, "off")]


def test_channel_calls_take_ch_pos_and_chs_by_name(rig: Rig) -> None:
    rig.clear_all()
    rig.set_channel(ch=7, pos="on")
    assert rig.get_channel(ch=7) == "on"
    assert rig.get_channels(chs=[7, 8]) == {7: "on", 8: "off"}


def test_channels_survive_closing_and_reconnecting(sim: str) -> None:
    # Closing never Clears: the Rig keeps the Channels for the next script.
    with Rig.connect(sim) as writer:
        writer.clear_all()
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
    rig.clear_all()
    with pytest.raises(ValueError, match=r"'of' isn't a Channel position.*\"on\" or \"off\""):
        rig.set_channel(1, "of")  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match="'ON'"):
        rig.set_channels({1: "on", 2: "ON"})  # pyright: ignore[reportArgumentType]
    assert rig.get_channel(1) == "off"


@pytest.mark.parametrize(
    ("verb", "args", "kwargs", "expected"),
    [
        pytest.param("set", (1, 5), {}, {**ALL_OFF, 1: "on", 3: "on", 5: "on", 16: "on"}, id="set"),
        pytest.param("clear", (3,), {}, {**ALL_OFF, 16: "on"}, id="clear"),
        pytest.param(
            "write",
            (),
            {"set": [1, 5], "clear": [3]},
            {**ALL_OFF, 1: "on", 5: "on", 16: "on"},
            id="write",
        ),
        pytest.param(
            "apply",
            (0x6742,),
            {},
            {**ALL_OFF, 2: "on", 7: "on", 9: "on", 10: "on", 11: "on", 14: "on", 15: "on"},
            id="apply",
        ),
        pytest.param(
            "apply",
            (0x6742,),
            {"mask": 0xFF00},
            {**ALL_OFF, 3: "on", 9: "on", 10: "on", 11: "on", 14: "on", 15: "on"},
            id="apply-masked",
        ),
    ],
)
def test_channel_verbs_change_only_the_named_channels(
    rig: Rig,
    verb: str,
    args: tuple[int, ...],
    kwargs: dict[str, Iterable[int] | int],
    expected: dict[int, str],
) -> None:
    rig.clear_all()
    rig.set_channels({3: "on", 16: "on"})
    getattr(rig, verb)(*args, **kwargs)
    assert rig.get_channels() == expected


def test_apply_ignores_state_outside_the_mask_after_a_clear(rig: Rig) -> None:
    rig.clear_all()
    rig.apply(0x6742, mask=0xFF00)
    assert rig.get_all() == 0x6700


def test_get_all_returns_an_immutable_integer_snapshot(rig: Rig) -> None:
    rig.apply(0x6742)
    state = rig.get_all()
    assert isinstance(state, itch.ChannelState)
    assert isinstance(state, int)
    assert state == 0x6742
    assert repr(state) == "ChannelState(0x6742, on=[2, 7, 9, 10, 11, 14, 15])"
    assert isinstance(state.on, frozenset)
    assert type(state | 1) is int
    with pytest.raises(AttributeError):
        state.note = "changed"  # pyright: ignore[reportAttributeAccessIssue]
    rig.clear_all()
    assert rig.get_all() == 0
    assert state == 0x6742
    rig.apply(state)
    assert rig.get_all() == 0x6742


@pytest.mark.parametrize("helper", ["ch", "state-get"])
def test_channel_helpers_reject_invalid_channels(helper: str) -> None:
    get_mask_or_state = itch.ch if helper == "ch" else itch.ChannelState(0).get
    with pytest.raises(ValueError, match=r"Channel 17 doesn't exist.*1 to 16"):
        get_mask_or_state(17)


@pytest.mark.parametrize(
    ("channels", "expected"),
    [((), 0x0000), ((1, 5), 0x0011), ((16,), 0x8000), ((1, 5, 9), 0x0111)],
)
def test_ch_builds_an_integer_mask(channels: tuple[int, ...], expected: int) -> None:
    result = itch.ch(*channels)
    assert type(result) is int
    assert result == expected
