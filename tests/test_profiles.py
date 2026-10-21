"""Profiles: driving a DUT by its settings against `itch-sim`."""

from collections.abc import Mapping

import pytest
from acme_widget import AcmeWidget
from scripted_rig import channel_writes, granting_writes

from itch import ItchError, Rig

ALL_OFF = dict.fromkeys(range(1, 17), "off")


def test_setting_a_field_writes_its_channels_and_leaves_the_rest(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    rig.clear_all()
    rig.set_channels({1: "on", 16: "on"})
    dut.resolution.set("1080p")
    assert rig.get_channels() == {**ALL_OFF, 1: "off", 2: "on", 16: "on"}
    assert dut.resolution.get() == "1080p"


def test_a_set_is_one_mask_write_over_the_fields_channels() -> None:
    with granting_writes() as peer, Rig.connect(peer.url) as rig:
        AcmeWidget(rig).mode.set("night", encoding=2)
    assert channel_writes(peer) == [(0b11_1000, 0b10_1000)]


def test_a_value_sets_encoding_1_unless_told_otherwise(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    dut.mode.set("night")
    assert rig.get_channels([4, 5, 6]) == {4: "on", 5: "off", 6: "off"}
    dut.mode.set("night", encoding=3)
    assert rig.get_channels([4, 5, 6]) == {4: "on", 5: "on", 6: "off"}


def test_get_reads_back_any_encoding_as_its_value(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    rig.set_channels({4: "on", 5: "off", 6: "on"})
    assert dut.mode.get() == "night"
    encoding = dut.mode.get_encoding()
    assert (encoding.value, encoding.number) == ("night", 2)


def test_an_alias_sets_its_value_and_reads_back_as_it(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    dut.mode.set("night")
    dut.mode.set("movie")
    assert rig.get_channels([4, 5, 6]) == {4: "off", 5: "off", 6: "off"}
    assert dut.mode.get() == "cinema"


def test_encodings_sweeps_every_encoding_of_a_value(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    seen: list[Mapping[int, str]] = []
    for encoding in dut.mode.encodings("night"):
        encoding.set()
        assert dut.mode.get_encoding().number == encoding.number
        seen.append(rig.get_channels([4, 5, 6]))
    assert seen == [
        {4: "on", 5: "off", 6: "off"},
        {4: "on", 5: "off", 6: "on"},
        {4: "on", 5: "on", 6: "off"},
    ]


def test_an_encoding_shows_its_value_number_and_positions(rig: Rig) -> None:
    encoding = AcmeWidget(rig).mode.encodings("night")[1]
    assert encoding.positions == ["on", "off", "on"]
    assert repr(encoding) == 'mode="night" Encoding 2 of 3 ["on", "off", "on"]'


def test_encodings_of_an_alias_are_its_values(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    assert [(e.value, e.number) for e in dut.mode.encodings("movie")] == [("cinema", 1)]


def test_all_encodings_sweeps_every_value_once(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    sweep = [(e.value, e.number) for e in dut.mode.all_encodings()]
    assert sweep == [("cinema", 1), ("sport", 1), ("night", 1), ("night", 2), ("night", 3)]
    for encoding in dut.mode.all_encodings():
        encoding.set()
        got = dut.mode.get_encoding()
        assert (got.value, got.number) == (encoding.value, encoding.number)


def test_an_unknown_value_suggests_the_closest_and_lists_the_choices(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    message = (
        r'mode has no Value "nigth"\. Did you mean "night"\? '
        r'Choose one of: "cinema", "sport", "night", "movie"\.'
    )
    rig.clear_all()
    with pytest.raises(ValueError, match=message):
        dut.mode.set("nigth")  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match=message):
        dut.mode.encodings("nigth")  # pyright: ignore[reportArgumentType]
    assert rig.get_channels() == ALL_OFF


@pytest.mark.parametrize(
    ("value", "encoding", "message"),
    [
        ("night", 4, r'"night" has 3 Encodings, so `encoding` must be 1 to 3, not 4\.'),
        ("night", 0, r'"night" has 3 Encodings, so `encoding` must be 1 to 3, not 0\.'),
        ("sport", 2, r'"sport" has 1 Encoding, so `encoding` must be 1, not 2\.'),
        ("movie", 2, r'"movie" has 1 Encoding, so `encoding` must be 1, not 2\.'),
    ],
)
def test_an_encoding_out_of_range_says_how_many_there_are(
    rig: Rig, value: str, encoding: int, message: str
) -> None:
    dut = AcmeWidget(rig)
    rig.clear_all()
    with pytest.raises(ValueError, match=message):
        dut.mode.set(value, encoding=encoding)  # pyright: ignore[reportArgumentType]
    assert rig.get_channels() == ALL_OFF


def test_get_raises_when_the_channels_match_no_value(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    rig.set_channels({4: "off", 5: "on", 6: "off"})
    message = (
        r'CH4, CH5, CH6 are \["off", "on", "off"\], which isn\'t any Value of AcmeWidget\.mode\.'
    )
    with pytest.raises(ItchError, match=message):
        dut.mode.get()
    with pytest.raises(ItchError, match=message):
        dut.mode.get_encoding()


def test_assigning_to_a_field_points_to_set(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with pytest.raises(AttributeError, match=r'Use dut\.mode\.set\("cinema"\) to change mode\.'):
        dut.mode = "cinema"  # pyright: ignore[reportAttributeAccessIssue]
    assert repr(dut.mode) == "<Field AcmeWidget.mode>"
