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


def script(address: str) -> None:
    dut = Rig.connect(address, AcmeWidget)
    dut.resolution.set("1080p")
    dut.mode.set("night", encoding=2)
    dut.mode.set("movie")
    for encoding in dut.mode.encodings("night"):
        encoding.set()
    for encoding in dut.mode.all_encodings():
        encoding.set()
    dut.apply(refresh="50hz", mode="night")

    assert_type(dut.resolution.get(), Resolution)
    assert_type(dut.mode.get(), Mode)
    assert_type(dut.mode.get_encoding(), Encoding[Mode])
    assert_type(dut.mode.encodings("movie"), list[Encoding[Mode]])
    assert_type(dut.mode.all_encodings()[0].value, Mode)


def typos_in_a_script(address: str) -> None:
    dut = Rig.connect(address, AcmeWidget)
    dut.mode.set("nigth")  # pyright: ignore[reportArgumentType]
    dut.mode.encodings("Night")  # pyright: ignore[reportArgumentType]
    dut.resolution.set("night")  # pyright: ignore[reportArgumentType]
    dut.mode.set(1)  # pyright: ignore[reportArgumentType]
    dut.mode.sett("night")  # pyright: ignore[reportAttributeAccessIssue]
    dut.mood.set("night")  # pyright: ignore[reportAttributeAccessIssue]


def assigning_a_value(address: str) -> None:
    Rig.connect(address, AcmeWidget).mode = "night"  # pyright: ignore[reportAttributeAccessIssue]


def removed_api_names(address: str) -> None:
    rig = Rig.connect(address)
    rig.set_channels({1: "on"})  # pyright: ignore[reportAttributeAccessIssue]
    rig.get_channels()  # pyright: ignore[reportAttributeAccessIssue]
    rig.close()  # pyright: ignore[reportAttributeAccessIssue]
    dut = Rig.connect(address, AcmeWidget)
    dut.batch()  # pyright: ignore[reportAttributeAccessIssue]


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


def connecting_with_a_profile() -> None:
    assert_type(Rig.connect("x"), Rig)
    assert_type(Rig.connect("x", AcmeWidget), AcmeWidget)
    assert_type(Rig.connect(profile=AcmeWidget), AcmeWidget)
    assert_type(Rig.connect("x", profile=AcmeWidget), AcmeWidget)
    dut = Rig.connect("x", AcmeWidget)
    for n in range(1, 17):
        dut.set(n)
    assert_type(dut.get(3), bool)
    assert_type(dut.get_all(), ChannelState)
    dut.apply(dut.get_all())
    dut.status()  # pyright: ignore[reportAttributeAccessIssue]


def connecting_with_context_managers() -> None:
    with Rig.connect("x", AcmeWidget) as dut:
        assert_type(dut, AcmeWidget)
        dut.disconnect()
    with Rig.connect("x") as rig:
        assert_type(rig, Rig)
        rig.disconnect()


def applying_fields_or_a_raw_channel_state() -> None:
    dut = Rig.connect("x", AcmeWidget)
    dut.apply(resolution="1080p", mode="night")
    dut.apply(mode=("night", 2))
    for enc in dut.mode.all_encodings():
        dut.apply(mode=enc)
    dut.apply(0x6742)
    dut.apply(0x6742, mask=0xFF00)
    dut.apply(0x6742, mode="night")  # pyright: ignore[reportCallIssue]
