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
            'e.g. "night": [1, 1].',
        ),
        (
            4,
            {"cinema": [0]},
            "Widget.mode: `channels` should be a list, e.g. channels=[4].",
        ),
        (
            [4],
            [[0], [1]],
            'Widget.mode: `values` should be a dict of names and positions, e.g. values={"night": '
            "[1]}.",
        ),
        (
            [4, 17],
            {"cinema": [0, 0]},
            "Widget.mode: Channel 17 doesn't exist. Channels are numbered 1 to 16.",
        ),
        (
            [0],
            {"cinema": [0]},
            "Widget.mode: Channel 0 doesn't exist. Channels are numbered 1 to 16.",
        ),
        (
            ["4"],
            {"cinema": [0]},
            "Widget.mode: Channel '4' doesn't exist. Channels are numbered 1 to 16.",
        ),
        (
            [4, 5, 4],
            {"cinema": [0, 0, 0]},
            "Widget.mode: Channel 4 is listed twice in `channels`.",
        ),
        (
            [4, 5],
            {"cinema": [0], "night": [1, 0]},
            'Widget.mode: "cinema" has 1 position, but mode uses 2 Channels (CH4, CH5). '
            "Give one 1 or 0 per Channel, in that order.",
        ),
        (
            [4, 5],
            {"night": [[1, 0], [1, 1, 0]]},
            'Widget.mode: "night" Encoding 2 has 3 positions, but mode uses 2 Channels (CH4, CH5). '
            "Give one 1 or 0 per Channel, in that order.",
        ),
        (
            [4, 5],
            {"cinema": ["off", "off"]},
            'Widget.mode: "cinema" has "off" for CH4. Use 1 for on or 0 for off.',
        ),
        (
            [4, 5],
            {"cinema": [0, 2]},
            'Widget.mode: "cinema" has 2 for CH5. Use 1 for on or 0 for off.',
        ),
        (
            [4, 5],
            {"cinema": [True, False]},
            'Widget.mode: "cinema" has True for CH4. Use 1 for on or 0 for off.',
        ),
        (
            [4, 5],
            {"cinema": "0 0"},
            'Widget.mode: Value "cinema" should be a list of 1 (on) or 0 (off), one per Channel, '
            'e.g. "cinema": [1, 1]. If it has several Encodings, put one such list per line '
            "inside another list.",
        ),
        (
            [4, 5],
            {"cinema": []},
            'Widget.mode: Value "cinema" should be a list of 1 (on) or 0 (off), one per Channel, '
            'e.g. "cinema": [1, 1]. If it has several Encodings, put one such list per line '
            "inside another list.",
        ),
        (
            [4, 5],
            {"night": [1, [1, 0]]},
            'Widget.mode: Value "night" mixes single positions and lists. Write either one list '
            "like [1, 1], or a list of such lists (one per Encoding).",
        ),
        (
            [4, 5],
            {720: [1, 0]},
            'Widget.mode: the Value name 720 needs quotes, like "720".',
        ),
        (
            [4, 5],
            {"cinema": [0, 0], "movie": [0, 0]},
            'Widget.mode: "cinema" and "movie" are both [0, 0]. If they are two names '
            'for the same setting, make "movie" an alias of "cinema".',
        ),
        (
            [4, 5],
            {"cinema": [0, 0], "night": [[1, 0], [0, 0]]},
            'Widget.mode: "cinema" and "night" Encoding 2 are both [0, 0]. If they are '
            'two names for the same setting, make "night" an alias of "cinema".',
        ),
        (
            [4, 5],
            {"night": [[1, 0], [1, 0]]},
            'Widget.mode: "night" Encoding 1 and "night" Encoding 2 are both [1, 0]. '
            "Remove one of them.",
        ),
        (
            [4, 5],
            {"cinema": [0, 0], "movie": alias("cinemaa")},
            'Widget.mode: alias "movie" points to "cinemaa", but there is no such Value. '
            'Did you mean "cinema"?',
        ),
        (
            [4, 5],
            {"cinema": [0, 0], "movie": alias("cinema"), "film": alias("movie")},
            'Widget.mode: alias "film" points to "movie", which is itself an alias. '
            'Point it at "cinema" instead.',
        ),
        (
            [4, 5],
            {"cinema": [0, 0], "movie": alias("movie")},
            'Widget.mode: alias "movie" points to itself. Point it at a Value, such as "cinema".',
        ),
        (
            [4, 5],
            {"cinema": [0, 0], "movie": alias("film"), "film": alias("movie")},
            'Widget.mode: alias "movie" points to "film", which is itself an alias. '
            'Point it at a Value, such as "cinema".',
        ),
    ],
)
def test_a_mistake_raises_a_plain_profile_error(channels: Any, values: Any, message: str) -> None:
    with pytest.raises(ProfileError, match=f"^{re.escape(message)}$"):
        define(channels, values)


def test_a_profile_error_is_an_itch_error() -> None:
    assert issubclass(ProfileError, ItchError)


def test_a_value_name_listed_twice_is_caught() -> None:
    def define_with_a_repeated_name() -> type[Profile]:
        class Widget(Profile):
            mode = field(
                channels=[4, 5],
                values={
                    "cinema": [0, 0],
                    "night": [1, 0],
                    "cinema": [1, 1],  # noqa: F601
                },
            )

        return Widget

    message = (
        'Widget.mode: the Value "cinema" is listed twice, and Python keeps only the last one. '
        "Give each Value its own name, or make one an alias."
    )
    with pytest.raises(ProfileError, match=f"^{re.escape(message)}$"):
        define_with_a_repeated_name()


def test_a_value_name_listed_twice_is_caught_in_an_annotated_field() -> None:
    def define_with_a_repeated_name() -> type[Profile]:
        class Widget(Profile):
            mode: Any = field([4], {"cinema": [0], "cinema": [1]})  # noqa: F601

        return Widget

    with pytest.raises(ProfileError, match='the Value "cinema" is listed twice'):
        define_with_a_repeated_name()


def test_a_profile_without_source_code_still_loads() -> None:
    namespace: dict[str, Any] = {"Profile": Profile, "field": field}
    exec('class Widget(Profile):\n    mode = field([4], {"cinema": [0]})', namespace)
    assert namespace["Widget"].mode.name == "mode"


@pytest.mark.parametrize(
    "name",
    [
        "set",
        "clear",
        "write",
        "apply",
        "set_all",
        "clear_all",
        "get",
        "get_all",
        "disconnect",
        "rig",
    ],
)
def test_reserved_field_names_fail_when_the_profile_is_defined(name: str) -> None:
    message = f"Widget.{name}: Field `{name}` clashes with a DUT method; give it another name."
    with pytest.raises(ProfileError, match=re.escape(message)):
        type("Widget", (Profile,), {name: field([1], {"enabled": [1]})})


@pytest.mark.parametrize("name", ["_mode", "__mode"])
def test_underscore_field_names_fail_when_the_profile_is_defined(name: str) -> None:
    namespace: dict[str, Any] = {"Profile": Profile, "field": field}
    with pytest.raises(ProfileError, match=r"starts with `_`.*give it another name"):
        # Compile a real class statement so Python mangles __mode before Profile sees it.
        exec(f'class Widget(Profile):\n    {name} = field([1], {{"enabled": [1]}})', namespace)


def test_rig_administration_names_remain_available_for_fields() -> None:
    class Widget(Profile):
        status = field([1], {"enabled": [1]})
        label = field([2], {"labelled": [1]})

    assert Widget.status.name == "status"
    assert Widget.label.name == "label"
