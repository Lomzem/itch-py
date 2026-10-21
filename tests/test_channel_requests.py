"""Channel verbs at the wire boundary: exact requests, fresh reads and validation."""

import re
from collections.abc import Iterable

import pytest
from scripted_rig import after_connecting, channel_writes, granting_writes

import itch
from itch import Rig
from itch._wire import Clear, GetChannels, GetChannelsReply, OkResponse, WriteChannels


@pytest.mark.parametrize(
    ("verb", "args", "kwargs", "expected"),
    [
        pytest.param("set", (1, 5), {}, (0x0011, 0x0011), id="set"),
        pytest.param("clear", (1, 5), {}, (0x0011, 0x0000), id="clear"),
        pytest.param("write", (), {"set": [1, 5], "clear": [3]}, (0x0015, 0x0011), id="write"),
        pytest.param("write", (), {"set": [1, 5]}, (0x0011, 0x0011), id="write-only-set"),
        pytest.param("write", (), {"clear": [3]}, (0x0004, 0x0000), id="write-only-clear"),
        pytest.param("apply", (0x6742,), {}, (0xFFFF, 0x6742), id="apply"),
        pytest.param("apply", (0x6742,), {"mask": 0xFF00}, (0xFF00, 0x6700), id="apply-masked"),
        pytest.param("apply", (0,), {}, (0xFFFF, 0x0000), id="apply-zero"),
        pytest.param("set_all", (), {}, (0xFFFF, 0xFFFF), id="set-all"),
    ],
)
def test_each_channel_verb_sends_one_exact_mask_write(
    verb: str,
    args: tuple[int, ...],
    kwargs: dict[str, Iterable[int] | int],
    expected: tuple[int, int],
) -> None:
    with granting_writes() as peer, Rig.connect(peer.url) as rig:
        getattr(rig, verb)(*args, **kwargs)
        assert channel_writes(peer) == [expected]
        getattr(rig, verb)(*args, **kwargs)
    assert channel_writes(peer) == [expected, expected]
    assert not any(isinstance(request.body, Clear) for request in peer.requests)


def test_clear_all_sends_one_clear_and_no_mask_write() -> None:
    with granting_writes() as peer, Rig.connect(peer.url) as rig:
        rig.clear_all()
        assert sum(isinstance(request.body, Clear) for request in peer.requests) == 1
        rig.clear_all()
    assert sum(isinstance(request.body, Clear) for request in peer.requests) == 2
    assert channel_writes(peer) == []


@pytest.mark.parametrize(
    ("verb", "args", "kwargs", "message"),
    [
        pytest.param("set", (), {}, "No Channels", id="empty-set"),
        pytest.param(
            "clear", (), {}, r"(?s)(?=.*No Channels)(?=.*clear_all\(\))", id="empty-clear"
        ),
        pytest.param("write", (), {}, "No Channels", id="empty-write"),
        pytest.param("write", (), {"set": [], "clear": []}, "No Channels", id="empty-write-lists"),
        pytest.param(
            "write", (), {"set": [1, 5], "clear": [3, 5]}, "both set and clear", id="overlap"
        ),
    ],
)
def test_empty_or_contradictory_changes_are_rejected_before_sending(
    verb: str, args: tuple[int, ...], kwargs: dict[str, list[int]], message: str
) -> None:
    with (
        granting_writes() as peer,
        Rig.connect(peer.url) as rig,
        pytest.raises(ValueError, match=message),
    ):
        getattr(rig, verb)(*args, **kwargs)
    assert not any(isinstance(request.body, WriteChannels | Clear) for request in peer.requests)


@pytest.mark.parametrize(
    ("verb", "channel"),
    [pytest.param("set", value, id=f"set-{value}") for value in (0, 17, -1, True, 1.0, "3")]
    + [
        pytest.param(verb, 17, id=f"{verb}-17")
        for verb in ("clear", "write-set", "write-clear", "get")
    ],
)
def test_invalid_channels_are_rejected_before_sending(verb: str, channel: int) -> None:
    message = rf"Channel {re.escape(repr(channel))} doesn't exist.*1 to 16"
    with granting_writes() as peer, Rig.connect(peer.url) as rig:

        def change() -> object:
            if verb == "write-set":
                return rig.write(set=iter([2, channel]), clear=[3])
            if verb == "write-clear":
                return rig.write(set=[2], clear=iter([3, channel]))
            if verb == "get":
                return rig.get(channel)
            return getattr(rig, verb)(2, channel)

        with pytest.raises(ValueError, match=message):
            change()
    # Rejected reads must not send GetChannels either.
    assert not any(
        isinstance(request.body, WriteChannels | Clear | GetChannels) for request in peer.requests
    )


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        pytest.param(argument, value, id=f"{argument}-{value!r}")
        for argument in ("state", "mask")
        for value in (-1, 0x10000, True, False, 1.0, "3")
    ]
    + [pytest.param("mask", 0, id="zero-mask")],
)
def test_apply_rejects_invalid_state_and_mask_before_sending(argument: str, value: int) -> None:
    state, mask = (value, 0xFFFF) if argument == "state" else (0x6742, value)
    with (
        granting_writes() as peer,
        Rig.connect(peer.url) as rig,
        pytest.raises(ValueError, match=argument),
    ):
        rig.apply(state, mask=mask)
    assert not any(isinstance(request.body, WriteChannels | Clear) for request in peer.requests)


@pytest.mark.parametrize("value", [-1, 0x10000, True, False, 1.0, "3"])
def test_channel_state_rejects_values_outside_the_16_bit_integer_domain(value: int) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - constructor error wording is unspecified
        itch.ChannelState(value)


def test_write_accepts_single_use_iterables() -> None:
    with granting_writes() as peer, Rig.connect(peer.url) as rig:
        rig.write(set=iter([1, 5]), clear=iter([3]))
    assert channel_writes(peer) == [(0x0015, 0x0011)]


def test_get_and_get_all_read_afresh_and_snapshot_access_stays_local() -> None:
    replies = iter([0x0000, 0x0004, 0x6742, 0x0000])
    with (
        after_connecting(
            lambda request: [OkResponse(request.request_id, GetChannelsReply(next(replies)))]
        ) as peer,
        Rig.connect(peer.url) as rig,
    ):
        assert rig.get(3) is False
        assert rig.get(3) is True
        saved = rig.get_all()
        assert saved == 0x6742
        assert rig.get_all() == 0x0000
        assert saved.get(2) is True
        assert saved.get(3) is False
        assert saved.on == frozenset({2, 7, 9, 10, 11, 14, 15})
    assert sum(isinstance(request.body, GetChannels) for request in peer.requests) == 4
    assert channel_writes(peer) == []
    assert not any(isinstance(request.body, Clear) for request in peer.requests)
