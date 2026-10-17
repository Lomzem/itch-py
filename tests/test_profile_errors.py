"""Profile mistakes are reported in plain English when the Profile is defined."""

import re
from typing import Any

import pytest

from itch import ItchError, Profile, ProfileError, alias, field


def define(channels: Any, values: Any) -> type[Profile]:
    """Defines a one-Field Profile, `Widget.mode`, the way a Profile file would."""

    class Widget(Profile):
        mode = field(channels=channels, values=values)

    return Widget


@pytest.mark.parametrize(
    ("channels", "values", "message"),
    [
        (
            [],
            {"cinema": []},
            "Widget.mode: `channels` is empty. List the Channels it uses, e.g. channels=[1, 2].",
        ),
        (
            [1, 2],
            {},
            "Widget.mode: `values` is empty. Give each Value a name and its positions, "
            'e.g. "night": ["on", "on"].',
        ),
        (
            [4, 17],
            {"cinema": ["off", "off"]},
            "Widget.mode: Channel 17 doesn't exist. Channels are numbered 1 to 16.",
        ),
        (
            [0],
            {"cinema": ["off"]},
            "Widget.mode: Channel 0 doesn't exist. Channels are numbered 1 to 16.",
        ),
        (
            ["4"],
            {"cinema": ["off"]},
            "Widget.mode: Channel '4' doesn't exist. Channels are numbered 1 to 16.",
        ),
        (
            [4, 5, 4],
            {"cinema": ["off", "off", "off"]},
            "Widget.mode: Channel 4 is listed twice in `channels`.",
        ),
        (
            [4, 5],
            {"cinema": ["off"], "night": ["on", "off"]},
            'Widget.mode: "cinema" has 1 position, but mode uses 2 Channels (CH4, CH5). '
            "Give one on/off per Channel, in that order.",
        ),
        (
            [4, 5],
            {"night": [["on", "off"], ["on", "on", "off"]]},
            'Widget.mode: "night" Encoding 2 has 3 positions, but mode uses 2 Channels (CH4, CH5). '
            "Give one on/off per Channel, in that order.",
        ),
        (
            [4, 5],
            {"cinema": ["off", "of"]},
            'Widget.mode: "cinema" has "of" for CH5. Use "on" or "off".',
        ),
        (
            [4, 5],
            {"cinema": "off off"},
            'Widget.mode: Value "cinema" should be a list of on/off, one per Channel, e.g. '
            '"cinema": ["on", "on"]. If it has several Encodings, put one such list per line '
            "inside another list.",
        ),
        (
            [4, 5],
            {"cinema": []},
            'Widget.mode: Value "cinema" should be a list of on/off, one per Channel, e.g. '
            '"cinema": ["on", "on"]. If it has several Encodings, put one such list per line '
            "inside another list.",
        ),
        (
            [4, 5],
            {"night": ["on", ["on", "off"]]},
            'Widget.mode: Value "night" mixes single positions and lists. Write either one list '
            'like ["on", "on"], or a list of such lists (one per Encoding).',
        ),
        (
            [4, 5],
            {720: ["on", "off"]},
            'Widget.mode: the Value name 720 needs quotes, like "720".',
        ),
        (
            [4, 5],
            {"cinema": ["off", "off"], "movie": ["off", "off"]},
            'Widget.mode: "cinema" and "movie" are both ["off", "off"]. If they are two names '
            'for the same setting, make "movie" an alias of "cinema".',
        ),
        (
            [4, 5],
            {"cinema": ["off", "off"], "night": [["on", "off"], ["off", "off"]]},
            'Widget.mode: "cinema" and "night" Encoding 2 are both ["off", "off"]. If they are '
            'two names for the same setting, make "night" an alias of "cinema".',
        ),
        (
            [4, 5],
            {"night": [["on", "off"], ["on", "off"]]},
            'Widget.mode: "night" Encoding 1 and "night" Encoding 2 are both ["on", "off"]. '
            "Remove one of them.",
        ),
        (
            [4, 5],
            {"cinema": ["off", "off"], "movie": alias("cinemaa")},
            'Widget.mode: alias "movie" points to "cinemaa", but there is no such Value. '
            'Did you mean "cinema"?',
        ),
        (
            [4, 5],
            {"cinema": ["off", "off"], "movie": alias("cinema"), "film": alias("movie")},
            'Widget.mode: alias "film" points to "movie", which is itself an alias. '
            'Point it at "cinema" instead.',
        ),
    ],
)
def test_a_mistake_raises_a_plain_profile_error(channels: Any, values: Any, message: str) -> None:
    with pytest.raises(ProfileError, match=f"^{re.escape(message)}$"):
        define(channels, values)


def test_a_profile_error_is_an_itch_error() -> None:
    assert issubclass(ProfileError, ItchError)
