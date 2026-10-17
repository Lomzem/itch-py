"""Batches and Fields that share Channels, against `itch-sim`."""

import pytest
from acme_widget import AcmeWidget
from scripted_rig import after_connecting

from itch import BatchConflictError, Profile, Rig, field
from itch._wire import (
    AcquireLease,
    AcquireLeaseReply,
    Message,
    OkResponse,
    ReleaseLease,
    ReleaseLeaseReply,
    ReplyBody,
    Request,
    RequestBody,
    WriteChannels,
    WriteChannelsReply,
)

ALL_OFF = dict.fromkeys(range(1, 17), "off")


def test_fields_sharing_a_channel_read_the_same_switch(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        dut.picture.set("bars")
        assert dut.tone.get() == "1khz"
        dut.mode.set("night")
        assert dut.refresh.get() == "50hz"


def test_a_batch_is_one_mask_write_when_the_block_ends() -> None:
    replies: dict[type[RequestBody], ReplyBody] = {
        AcquireLease: AcquireLeaseReply(10_000),
        WriteChannels: WriteChannelsReply(0),
        ReleaseLease: ReleaseLeaseReply(),
    }

    def answer(request: Request) -> list[Message]:
        return [OkResponse(request.request_id, replies[type(request.body)])]

    with after_connecting(answer) as peer, Rig.connect(peer.url) as rig:
        dut = AcmeWidget(rig)
        with rig.session(), dut.batch():
            dut.resolution.set("4k")
            dut.refresh.set("50hz")
            dut.mode.set("night", encoding=2)
            assert not [r for r in peer.requests if isinstance(r.body, WriteChannels)]
        writes = [r.body for r in peer.requests if isinstance(r.body, WriteChannels)]
    assert [(w.mask, w.values) for w in writes] == [(0b11_1011, 0b10_1011)]


def test_a_batch_sets_every_field_together(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        rig.clear()
        rig.set_channel(16, "on")
        with dut.batch():
            dut.resolution.set("1080p")
            dut.picture.set("bars")
            dut.mode.set("sport")
        assert rig.get_channels() == {**ALL_OFF, 2: "on", 3: "on", 6: "on", 16: "on"}


def test_a_field_set_twice_in_a_batch_keeps_the_last_value(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        with dut.batch():
            dut.resolution.set("720p")
            dut.mode.set("night")
            dut.resolution.set("4k")
        assert dut.resolution.get() == "4k"
        assert dut.mode.get() == "night"


def test_a_field_set_twice_may_change_its_mind_on_a_shared_channel(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        with dut.batch():
            dut.refresh.set("50hz")
            dut.refresh.set("60hz")
            dut.mode.set("sport")
        assert (dut.refresh.get(), dut.mode.get()) == ("60hz", "sport")


def test_fields_that_agree_on_a_shared_channel_are_fine_in_a_batch(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        with dut.batch():
            dut.refresh.set("50hz")
            dut.mode.set("night")
            dut.picture.set("bars")
            dut.tone.set("1khz")
        assert rig.get_channels([3, 4, 5, 6]) == {3: "on", 4: "on", 5: "off", 6: "off"}


def test_fields_that_disagree_on_a_shared_channel_change_nothing(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    message = (
        r'CH4: refresh="60hz" needs off, but mode="night" needs on\. Set only one of them in a '
        r"batch, or pick Values that agree\. No Channels were changed\."
    )
    with rig.session():
        rig.clear()
        with pytest.raises(BatchConflictError, match=message):
            batch_refresh_and_mode(dut)
        assert rig.get_channels() == ALL_OFF


def test_a_conflict_names_the_field_set_first_first(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        rig.clear()
        message = r'CH3: tone="1khz" needs on, but picture="black" needs off\.'
        with pytest.raises(BatchConflictError, match=message):
            batch_tone_and_picture(dut)
        assert rig.get_channels() == ALL_OFF


def test_an_error_inside_a_batch_changes_nothing(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        rig.clear()
        with pytest.raises(ValueError, match="no Value"):
            batch_with_a_typo(dut)
        assert rig.get_channels() == ALL_OFF
        dut.resolution.set("720p")
        assert rig.get_channels([1, 2]) == {1: "on", 2: "off"}


def test_printing_a_dut_shows_every_fields_value(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        rig.clear()
        dut.resolution.set("1080p")
        dut.mode.set("night", encoding=2)
    assert str(dut) == (
        'AcmeWidget(resolution="1080p", picture="black", tone="silent", refresh="50hz", '
        'mode="night" (Encoding 2))'
    )


def test_printing_a_dut_shows_the_positions_of_a_field_that_matches_no_value(rig: Rig) -> None:
    dut = AcmeWidget(rig)
    with rig.session():
        rig.clear()
    assert str(dut).startswith('AcmeWidget(resolution=["off", "off"] (no Value), picture="black"')


def batch_refresh_and_mode(dut: AcmeWidget) -> None:
    with dut.batch():
        dut.resolution.set("4k")
        dut.refresh.set("60hz")
        dut.mode.set("night")


def batch_tone_and_picture(dut: AcmeWidget) -> None:
    with dut.batch():
        dut.tone.set("1khz")
        dut.picture.set("black")


def batch_with_a_typo(dut: AcmeWidget) -> None:
    with dut.batch():
        dut.resolution.set("4k")
        dut.mode.set("nigth")  # pyright: ignore[reportArgumentType]


class Overlapping(Profile):
    left = field(channels=[2], values={"low": ["off"], "high": ["on"]})
    right = field(channels=[1], values={"low": ["off"], "high": ["on"]})
    both = field(channels=[1, 2], values={"mixed": ["on", "off"], "up": ["on", "on"]})


def test_a_conflict_on_several_channels_names_the_first_and_who_set_it(rig: Rig) -> None:
    dut = Overlapping(rig)
    message = (
        r'^CH1: right="low" needs off, but both="up" needs on\. Set only one of them in a batch, '
        r"or pick Values that agree\. No Channels were changed\.$"
    )
    with rig.session():
        rig.clear()
        with pytest.raises(BatchConflictError, match=message):
            batch_left_right_both(dut)
        assert rig.get_channels() == ALL_OFF


def batch_left_right_both(dut: Overlapping) -> None:
    with dut.batch():
        dut.left.set("low")
        dut.right.set("low")
        dut.both.set("up")


class Inherited(AcmeWidget):
    hdmi = field(channels=[8], values={"hdmi off": ["off"], "hdmi on": ["on"]})


def test_printing_a_dut_shows_inherited_fields_too(rig: Rig) -> None:
    dut = Inherited(rig)
    with rig.session():
        rig.clear()
        dut.resolution.set("4k")
    assert str(dut).startswith('Inherited(resolution="4k", picture="black"')
    assert str(dut).endswith('mode="cinema", hdmi="hdmi off")')
