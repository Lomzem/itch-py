"""`rig.status()`: the Rig's health since boot."""

import dataclasses
from datetime import timedelta

import pytest
from scripted_rig import ScriptedRig, after_connecting

from itch import Rig, Status
from itch._wire import GetStatusReply, OkResponse

AFTER_A_PANIC = GetStatusReply(
    uptime_ms=3_723_000,
    reset_reason=0x03,
    last_panic="src/main.rs:88:5",
    holder="qa@bench-pc acme_test.py",
    crc_failures=1,
    oversized_frames=2,
    malformed_frames=3,
    dropped_logs=4,
    expander_faults=5,
    usb_tx_dropped=6,
)


def reporting(status: GetStatusReply) -> ScriptedRig:
    return after_connecting(lambda request: [OkResponse(request.request_id, status)])


def test_simulator_reports_a_fresh_power_on(rig: Rig) -> None:
    first = rig.status()
    assert first.reset_reason == "ChipPowerOn"
    assert first.last_panic is None
    assert first.holder is None
    assert rig.status().uptime >= first.uptime


def test_status_shows_a_holder_during_a_session(rig: Rig) -> None:
    with rig.session():
        assert rig.status().holder is not None
    assert rig.status().holder is None


def test_status_reports_every_field() -> None:
    with reporting(AFTER_A_PANIC) as peer, Rig.connect(peer.url) as rig:
        assert rig.status() == Status(
            uptime=timedelta(hours=1, minutes=2, seconds=3),
            reset_reason="CoreSw",
            last_panic="src/main.rs:88:5",
            holder="qa@bench-pc acme_test.py",
            crc_failures=1,
            oversized_frames=2,
            malformed_frames=3,
            dropped_logs=4,
            expander_faults=5,
            usb_tx_dropped=6,
        )


@pytest.mark.parametrize(
    ("code", "name"),
    [(0x01, "ChipPowerOn"), (0x16, "CoreUsbJtag"), (0x00, "unknown"), (0x2A, "unknown (0x2A)")],
)
def test_reset_reason_is_named_where_known(code: int, name: str) -> None:
    status = dataclasses.replace(AFTER_A_PANIC, reset_reason=code)
    with reporting(status) as peer, Rig.connect(peer.url) as rig:
        assert rig.status().reset_reason == name
