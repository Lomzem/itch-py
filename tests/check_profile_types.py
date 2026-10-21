"""What Pylance shows a QA engineer using a Profile. Pyright checks this file; pytest never runs it.

It runs in basic mode, as QA's editors do. Each `# pyright: ignore[...]` marks a mistake the editor
must flag: with `reportUnnecessaryTypeIgnoreComment`, Pyright fails if one stops being an error.
"""
# pyright: basic
# pyright: reportUnnecessaryTypeIgnoreComment=error

from typing import Literal, assert_type

from acme_widget import AcmeWidget

from itch import ChannelState, Encoding, Profile, Rig, ch, field

# Value completion offers exactly the names a parameter of this type accepts, aliases included.
Mode = Literal["cinema", "sport", "night", "movie"]
Resolution = Literal["720p", "1080p", "4k"]


def script(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    dut.resolution.set("1080p")
    dut.mode.set("night", encoding=2)
    dut.mode.set("movie")
    for encoding in dut.mode.encodings("night"):
        encoding.set()
    for encoding in dut.mode.all_encodings():
        encoding.set()
    with dut.batch():
        dut.refresh.set("50hz")
        dut.mode.set("night")

    assert_type(dut.resolution.get(), Resolution)
    assert_type(dut.mode.get(), Mode)
    assert_type(dut.mode.get_encoding(), Encoding[Mode])
    assert_type(dut.mode.encodings("movie"), list[Encoding[Mode]])
    assert_type(dut.mode.all_encodings()[0].value, Mode)


def typos_in_a_script(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    dut.mode.set("nigth")  # pyright: ignore[reportArgumentType]
    dut.mode.encodings("Night")  # pyright: ignore[reportArgumentType]
    dut.resolution.set("night")  # pyright: ignore[reportArgumentType]
    dut.mode.set(1)  # pyright: ignore[reportArgumentType]
    dut.mode.sett("night")  # pyright: ignore[reportAttributeAccessIssue]
    dut.mood.set("night")  # pyright: ignore[reportAttributeAccessIssue]
    with dut.batch():
        dut.mode.set("nigth")  # pyright: ignore[reportArgumentType]


def assigning_a_value(rig: Rig) -> None:
    AcmeWidget(rig).mode = "night"  # pyright: ignore[reportAttributeAccessIssue]


class Mistakes(Profile):
    """Mistakes the editor flags while a Profile is written. Run, each raises `ProfileError`."""

    position_typo = field(channels=[1, 2], values={"a": ["on", "of"]})  # pyright: ignore[reportArgumentType]
    encoding_typo = field(channels=[1], values={"a": [["on"], ["of"]]})  # pyright: ignore[reportArgumentType]
    one_string = field(channels=[1, 2], values={"a": "on off"})  # pyright: ignore[reportArgumentType]
    unquoted_name = field(channels=[1], values={720: ["on"]})  # pyright: ignore[reportArgumentType]


def channel_verbs_with_computed_channel_numbers(rig: Rig) -> None:
    for n in range(1, 17):
        rig.set(n)
        rig.clear(n)
        rig.write(set=[n], clear=[n + 1])
    assert_type(rig.get(3), bool)
    assert_type(rig.get_all(), ChannelState)
    assert_type(ch(1, 5), int)
