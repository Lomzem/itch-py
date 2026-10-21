"""Setting and reading Channels against `itch-sim`."""

from collections.abc import Iterable

import pytest

import itch
from itch import Rig


def test_set_all_and_clear_all_turn_every_channel_on_then_off(rig: Rig) -> None:
    rig.set_all()
    assert rig.get_all() == 0xFFFF
    rig.clear_all()
    assert rig.get_all() == 0x0000


@pytest.mark.parametrize(
    ("verb", "args", "kwargs", "expected"),
    [
        pytest.param("set", (1, 5), {}, 0x8015, id="set"),
        pytest.param("clear", (3,), {}, 0x8000, id="clear"),
        pytest.param(
            "write",
            (),
            {"set": [1, 5], "clear": [3]},
            0x8011,
            id="write",
        ),
        pytest.param(
            "apply",
            (0x6742,),
            {},
            0x6742,
            id="apply",
        ),
        pytest.param(
            "apply",
            (0x6742,),
            {"mask": 0xFF00},
            0x6704,
            id="apply-masked",
        ),
    ],
)
def test_channel_verbs_change_only_the_named_channels(
    rig: Rig,
    verb: str,
    args: tuple[int, ...],
    kwargs: dict[str, Iterable[int] | int],
    expected: int,
) -> None:
    rig.clear_all()
    rig.set(3, 16)
    getattr(rig, verb)(*args, **kwargs)
    assert rig.get_all() == expected


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
