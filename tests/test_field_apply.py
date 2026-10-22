"""Apply Field settings through a connected DUT, with atomic validation and Mask writes."""

from collections.abc import Callable
from typing import cast

import pytest
from acme_widget import AcmeWidget
from scripted_rig import channel_writes, granting_writes

from itch import BatchConflictError, Profile, Rig, field


def test_field_apply_sends_one_mask_write_over_the_union_of_channels() -> None:
    with granting_writes() as peer, Rig.connect(peer.url, AcmeWidget) as dut:
        dut.apply(resolution="4k", refresh="50hz", mode=("night", 2))
    assert channel_writes(peer) == [(0b11_1011, 0b10_1011)]


@pytest.mark.parametrize(
    ("setting", "value", "number", "state"),
    [
        pytest.param("night", "night", 1, 0x8008, id="value-defaults-to-encoding-1"),
        pytest.param("movie", "cinema", 1, 0x8000, id="alias-reads-back-as-value"),
        pytest.param(("night", 2), "night", 2, 0x8028, id="numbered-encoding"),
    ],
)
def test_field_apply_reads_back_the_setting_and_preserves_unnamed_channels(
    sim: str, setting: str | tuple[str, int], value: str, number: int, state: int
) -> None:
    with Rig.connect(sim, AcmeWidget) as dut:
        dut.clear_all()
        # Start with the Field's Channels on, so even the all-off Alias must change the Rig.
        dut.set(4, 5, 6, 16)
        dut.apply(mode=setting)
        assert dut.get_all() == state
        assert dut.mode.get() == value
        got = dut.mode.get_encoding()
        assert (got.value, got.number) == (value, number)


def test_field_apply_accepts_every_encoding_in_a_sweep(sim: str) -> None:
    with Rig.connect(sim, AcmeWidget) as dut:
        dut.clear_all()
        dut.set(16)
        for encoding in dut.mode.all_encodings():
            dut.apply(mode=encoding)
            got = dut.mode.get_encoding()
            assert (got.value, got.number) == (encoding.value, encoding.number)
            assert dut.get_all() & 0xFFC7 == 0x8000


@pytest.mark.parametrize(
    ("args", "settings", "error", "message"),
    [
        pytest.param(
            (),
            {"resolution": "4k", "mode": "nigth"},
            ValueError,
            r'mode has no Value "nigth"\. Did you mean "night"\?',
            id="unknown-value-after-valid-field",
        ),
        pytest.param(
            (),
            {"resolution": "4k", "mode": ("night", 4)},
            ValueError,
            r'mode: "night" has 3 Encodings, so `encoding` must be 1 to 3, not 4\.',
            id="encoding-out-of-range-after-valid-field",
        ),
        pytest.param(
            (),
            {"resolution": "4k", "mood": "night"},
            ValueError,
            r'AcmeWidget has no Field "mood"\. Did you mean "mode"\? '
            r"Choose one of: resolution, picture, tone, refresh, mode\.",
            id="unknown-field-after-valid-field",
        ),
        *[
            pytest.param(
                (),
                {"resolution": "4k", "mode": setting},
                TypeError,
                r"mode should be a Value, a \(Value, number\) tuple or an Encoding, not ",
                id=name,
            )
            for name, setting in [
                ("integer-after-valid-field", 1),
                ("short-tuple-after-valid-field", ("night",)),
                ("long-tuple-after-valid-field", ("night", 2, 3)),
            ]
        ],
        pytest.param(
            (),
            {"refresh": "60hz", "mode": "night"},
            BatchConflictError,
            r'CH4: refresh="60hz" needs off, but mode="night" needs on\. '
            r"Set only one of them, or pick Values that agree\. No Channels were changed\.",
            id="shared-channel-conflict",
        ),
        pytest.param(
            (),
            {"tone": "1khz", "picture": "black"},
            BatchConflictError,
            r'CH3: tone="1khz" needs on, but picture="black" needs off\.',
            id="conflict-names-first-specified-field-first",
        ),
        pytest.param(
            (),
            {},
            ValueError,
            r"apply\(\) needs a Channel state or at least one Field",
            id="no-arguments",
        ),
        *[
            pytest.param(
                (0x6742,),
                settings,
                TypeError,
                r"apply\(\) takes either a Channel state .* or Fields .*, not both",
                id=name,
            )
            for name, settings in [
                ("raw-state-and-fields", {"mode": "night"}),
                ("masked-raw-state-and-fields", {"mask": 0xFF00, "mode": "night"}),
            ]
        ],
    ],
)
def test_field_apply_rejects_the_entire_call_without_writing(
    args: tuple[int, ...], settings: dict[str, object], error: type[Exception], message: str
) -> None:
    with granting_writes() as peer, Rig.connect(peer.url, AcmeWidget) as dut:
        apply = cast(Callable[..., None], dut.apply)
        with pytest.raises(error, match=message):
            apply(*args, **settings)
    assert channel_writes(peer) == []


def test_field_apply_rejects_an_encoding_of_another_field_without_writing() -> None:
    with granting_writes() as peer, Rig.connect(peer.url, AcmeWidget) as dut:
        encoding = dut.refresh.encodings("50hz")[0]
        with pytest.raises(ValueError, match=r"mode: .* is an Encoding of refresh, not mode\."):
            dut.apply(resolution="4k", mode=encoding)
    assert channel_writes(peer) == []


class Overlapping(Profile):
    left = field(channels=[2], values={"low": [0], "high": [1]})
    right = field(channels=[1], values={"low": [0], "high": [1]})
    both = field(channels=[1, 2], values={"mixed": [1, 0], "up": [1, 1]})


def test_field_apply_names_the_first_conflicting_channel_and_who_set_it() -> None:
    message = (
        r'^CH1: right="low" needs off, but both="up" needs on\. Set only one of them, '
        r"or pick Values that agree\. No Channels were changed\.$"
    )
    with (
        granting_writes() as peer,
        Rig.connect(peer.url, Overlapping) as dut,
        pytest.raises(BatchConflictError, match=message),
    ):
        dut.apply(left="low", right="low", both="up")
    assert channel_writes(peer) == []
