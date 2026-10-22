"""Profiles: driving a DUT by its settings against `itch-sim`."""

import re

import pytest
from acme_widget import AcmeWidget
from scripted_rig import channel_writes, granting_writes

from itch import ItchError, Rig, field


def test_setting_a_field_writes_its_channels_and_leaves_the_rest(dut: AcmeWidget) -> None:
    dut.clear_all()
    dut.set(1, 16)
    dut.resolution.set("1080p")
    assert dut.get_all() == 0x8002
    assert dut.resolution.get() == "1080p"


def test_a_set_is_one_mask_write_over_the_fields_channels() -> None:
    with granting_writes() as peer, Rig.connect(peer.url, AcmeWidget) as dut:
        dut.mode.set("night", encoding=2)
    assert channel_writes(peer) == [(0b11_1000, 0b10_1000)]


def test_a_value_sets_encoding_1_unless_told_otherwise(dut: AcmeWidget) -> None:
    dut.mode.set("night")
    assert dut.get_all() & 0x0038 == 0x0008
    dut.mode.set("night", encoding=3)
    assert dut.get_all() & 0x0038 == 0x0018


def test_get_reads_back_any_encoding_as_its_value(dut: AcmeWidget) -> None:
    dut.apply(0x0028, mask=0x0038)
    assert dut.mode.get() == "night"
    encoding = dut.mode.get_encoding()
    assert (encoding.value, encoding.number) == ("night", 2)


def test_an_alias_sets_its_value_and_reads_back_as_it(dut: AcmeWidget) -> None:
    dut.mode.set("night")
    dut.mode.set("movie")
    assert dut.get_all() & 0x0038 == 0x0000
    assert dut.mode.get() == "cinema"


def test_encodings_sweeps_every_encoding_of_a_value(dut: AcmeWidget) -> None:
    seen: list[int] = []
    for encoding in dut.mode.encodings("night"):
        encoding.set()
        assert dut.mode.get_encoding().number == encoding.number
        seen.append(dut.get_all() & 0x0038)
    assert seen == [0x0008, 0x0028, 0x0018]


def test_an_encoding_shows_its_value_number_and_positions(dut: AcmeWidget) -> None:
    encoding = dut.mode.encodings("night")[1]
    assert encoding.positions == [1, 0, 1]
    assert repr(encoding) == 'mode="night" Encoding 2 of 3 [1, 0, 1]'


def test_encodings_of_an_alias_are_its_values(dut: AcmeWidget) -> None:
    assert [(e.value, e.number) for e in dut.mode.encodings("movie")] == [("cinema", 1)]


def test_all_encodings_sweeps_every_value_once(dut: AcmeWidget) -> None:
    sweep = [(e.value, e.number) for e in dut.mode.all_encodings()]
    assert sweep == [("cinema", 1), ("sport", 1), ("night", 1), ("night", 2), ("night", 3)]


def test_an_unknown_value_suggests_the_closest_and_lists_the_choices(dut: AcmeWidget) -> None:
    message = (
        r'mode has no Value "nigth"\. Did you mean "night"\? '
        r'Choose one of: "cinema", "sport", "night", "movie"\.'
    )
    dut.clear_all()
    with pytest.raises(ValueError, match=message):
        dut.mode.set("nigth")  # pyright: ignore[reportArgumentType]
    with pytest.raises(ValueError, match=message):
        dut.mode.encodings("nigth")  # pyright: ignore[reportArgumentType]
    assert dut.get_all() == 0x0000


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
    dut: AcmeWidget, value: str, encoding: int, message: str
) -> None:
    dut.clear_all()
    with pytest.raises(ValueError, match=message):
        dut.mode.set(value, encoding=encoding)  # pyright: ignore[reportArgumentType]
    assert dut.get_all() == 0x0000


def test_get_raises_when_the_channels_match_no_value(dut: AcmeWidget) -> None:
    dut.apply(0x0010, mask=0x0038)
    message = r"CH4, CH5, CH6 are \[0, 1, 0\], which isn't any Value of AcmeWidget\.mode\."
    with pytest.raises(ItchError, match=message):
        dut.mode.get()
    with pytest.raises(ItchError, match=message):
        dut.mode.get_encoding()


def test_assigning_to_a_field_points_to_apply_and_set(dut: AcmeWidget) -> None:
    with pytest.raises(AttributeError) as raised:
        dut.mode = "cinema"  # pyright: ignore[reportAttributeAccessIssue]
    message = str(raised.value)
    assert re.search(r'dut\.apply\(mode="cinema"\)', message), message
    assert re.search(r'dut\.mode\.set\("cinema"\)', message), message
    assert repr(dut.mode) == "<Field AcmeWidget.mode>"


def test_fields_sharing_a_channel_read_the_same_switch(dut: AcmeWidget) -> None:
    dut.picture.set("bars")
    assert dut.tone.get() == "1khz"
    dut.mode.set("night")
    assert dut.refresh.get() == "50hz"


def test_printing_a_dut_shows_the_positions_of_a_field_that_matches_no_value(
    dut: AcmeWidget,
) -> None:
    dut.clear_all()
    assert str(dut).startswith('AcmeWidget(resolution=[0, 0] (no Value), picture="black"')


class Inherited(AcmeWidget):
    hdmi = field(channels=[8], values={"hdmi off": [0], "hdmi on": [1]})


def test_printing_a_dut_shows_inherited_fields_too(sim: str) -> None:
    with Rig.connect(sim, Inherited) as dut:
        dut.clear_all()
        dut.resolution.set("4k")
        assert str(dut).startswith('Inherited(resolution="4k", picture="black"')
        assert str(dut).endswith('mode="cinema", hdmi="hdmi off")')
