"""Setting and reading Channels against `itch-sim`."""

import pytest
from scripted_rig import ACME_HELLO, ScriptedRig

from itch import ItchError, LeaseRequiredError, Rig
from itch._wire import Hello, OkResponse, Request

ALL_OFF = dict.fromkeys(range(1, 17), "off")


def test_sets_and_reads_one_channel(rig: Rig) -> None:
    with rig.session():
        rig.clear()
        rig.set_channel(3, "on")
        assert rig.get_channel(3) == "on"
        assert rig.get_channel(4) == "off"
        rig.set_channel(3, "off")
        assert rig.get_channel(3) == "off"


def test_set_channels_changes_only_the_listed_channels(rig: Rig) -> None:
    with rig.session():
        rig.clear()
        rig.set_channels({1: "on", 2: "on"})
        rig.set_channels({1: "off", 16: "on"})
        assert rig.get_channels() == {**ALL_OFF, 2: "on", 16: "on"}


def test_clear_turns_every_channel_off(rig: Rig) -> None:
    with rig.session():
        for ch in range(1, 17):
            rig.set_channel(ch, "on")
        assert set(rig.get_channels().values()) == {"on"}
        rig.clear()
        assert rig.get_channels() == ALL_OFF


def test_get_channels_reads_the_listed_channels_in_order(rig: Rig) -> None:
    with rig.session():
        rig.clear()
        rig.set_channel(16, "on")
    assert list(rig.get_channels([16, 1]).items()) == [(16, "on"), (1, "off")]


def test_reads_work_outside_a_session_and_see_the_last_writes(sim: str) -> None:
    with Rig.connect(sim) as writer, writer.session():
        writer.clear()
        writer.set_channels({5: "on", 6: "on"})
    with Rig.connect(sim) as reader:
        assert reader.get_channels() == {**ALL_OFF, 5: "on", 6: "on"}


def test_writes_outside_a_session_raise_lease_required(rig: Rig) -> None:
    with rig.session():
        pass
    for write in (lambda: rig.set_channel(1, "on"), lambda: rig.set_channels({}), rig.clear):
        with pytest.raises(LeaseRequiredError, match=r"rig\.session\(\)"):
            write()


def test_a_write_outside_a_session_makes_no_round_trip() -> None:
    def answer(request: Request) -> list[OkResponse]:
        assert request.body == Hello()
        return [OkResponse(request.request_id, ACME_HELLO)]

    with ScriptedRig(answer) as peer, Rig.connect(peer.url) as rig:
        with pytest.raises(LeaseRequiredError):
            rig.set_channel(1, "on")
        assert len(peer.requests) == 1
    assert issubclass(LeaseRequiredError, ItchError)


@pytest.mark.parametrize("channel", [0, 17, -1])
def test_a_channel_outside_1_to_16_raises_value_error(rig: Rig, channel: int) -> None:
    message = rf"Channel {channel} doesn't exist.*1 to 16"
    with pytest.raises(ValueError, match=message):
        rig.get_channel(channel)
    with pytest.raises(ValueError, match=message):
        rig.get_channels([1, channel])
    with rig.session():
        with pytest.raises(ValueError, match=message):
            rig.set_channel(channel, "on")
        with pytest.raises(ValueError, match=message):
            rig.set_channels({1: "on", channel: "off"})


def test_an_invalid_position_raises_value_error(rig: Rig) -> None:
    with rig.session():
        rig.clear()
        with pytest.raises(ValueError, match=r"'of' isn't a Channel position.*\"on\" or \"off\""):
            rig.set_channel(1, "of")  # pyright: ignore[reportArgumentType]
        with pytest.raises(ValueError, match="'ON'"):
            rig.set_channels({1: "on", 2: "ON"})  # pyright: ignore[reportArgumentType]
        assert rig.get_channel(1) == "off"
