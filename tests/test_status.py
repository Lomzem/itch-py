"""`rig.status()`: the Rig's health since boot, its Lock and its network."""

import dataclasses
from datetime import timedelta
from ipaddress import IPv4Address, IPv4Interface

import pytest
from scripted_rig import ScriptedRig, after_connecting

from itch import AddressMode, Link, Rig, Status
from itch._wire import GetStatusReply, OkResponse

AFTER_A_PANIC = GetStatusReply(
    uptime_ms=3_723_000,
    reset_reason=0x03,
    last_panic="src/main.rs:88:5",
    crc_failures=1,
    oversized_frames=2,
    malformed_frames=3,
    dropped_logs=4,
    expander_faults=5,
    usb_tx_dropped=6,
    holder="alice@ws3",
    wifi_configured=True,
    ssid="ExampleRigNet",
    link=2,
    current_address=bytes([192, 0, 2, 10]),
    mode=1,
    address=bytes([192, 0, 2, 10]),
    prefix=24,
    gateway=bytes([192, 0, 2, 1]),
)
"""The `messages.md` example: Locked by `alice@ws3`, connected at a static address."""


def reporting(status: GetStatusReply) -> ScriptedRig:
    return after_connecting(lambda request: [OkResponse(request.request_id, status)])


def test_simulator_reports_a_fresh_power_on_unlocked_without_wifi(sim: str) -> None:
    with Rig.connect(sim, lock=False) as rig:
        first = rig.status()
        later = rig.status()
    assert first.reset_reason == "ChipPowerOn"
    assert first.last_panic is None
    assert first.holder is None
    assert not first.wifi_configured
    assert first.ssid is None
    assert first.link is Link.OFF
    assert first.current_address is None
    assert first.address_mode is AddressMode.DHCP
    assert first.static_address is None
    assert first.gateway is None
    assert later.uptime >= first.uptime


def test_status_reports_every_field() -> None:
    with reporting(AFTER_A_PANIC) as peer, Rig.connect(peer.url) as rig:
        assert rig.status() == Status(
            uptime=timedelta(hours=1, minutes=2, seconds=3),
            reset_reason="CoreSw",
            last_panic="src/main.rs:88:5",
            crc_failures=1,
            oversized_frames=2,
            malformed_frames=3,
            dropped_logs=4,
            expander_faults=5,
            usb_tx_dropped=6,
            holder="alice@ws3",
            wifi_configured=True,
            ssid="ExampleRigNet",
            link=Link.CONNECTED,
            current_address=IPv4Address("192.0.2.10"),
            address_mode=AddressMode.STATIC,
            static_address=IPv4Interface("192.0.2.10/24"),
            gateway=IPv4Address("192.0.2.1"),
        )


def test_status_reports_a_joining_link_and_a_static_address_without_a_gateway() -> None:
    joining = dataclasses.replace(AFTER_A_PANIC, link=1, current_address=bytes(4), gateway=bytes(4))
    with reporting(joining) as peer, Rig.connect(peer.url) as rig:
        status = rig.status()
    assert (status.link, status.current_address) == (Link.JOINING, None)
    assert (status.static_address, status.gateway) == (IPv4Interface("192.0.2.10/24"), None)


@pytest.mark.parametrize(
    ("code", "name"),
    [(0x01, "ChipPowerOn"), (0x16, "CoreUsbJtag"), (0x00, "unknown"), (0x2A, "unknown (0x2A)")],
)
def test_reset_reason_is_named_where_known(code: int, name: str) -> None:
    status = dataclasses.replace(AFTER_A_PANIC, reset_reason=code)
    with reporting(status) as peer, Rig.connect(peer.url) as rig:
        assert rig.status().reset_reason == name
