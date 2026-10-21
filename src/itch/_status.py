from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from ipaddress import IPv4Address, IPv4Interface

from itch import _wire

_RESET_REASONS = {
    0x01: "ChipPowerOn",
    0x03: "CoreSw",
    0x05: "CoreDeepSleep",
    0x07: "CoreMwdt0",
    0x08: "CoreMwdt1",
    0x09: "CoreRtcWdt",
    0x0B: "CpuMwdt0",
    0x0C: "CpuSw",
    0x0D: "CpuRtcWdt",
    0x0F: "SysBrownOut",
    0x10: "SysRtcWdt",
    0x11: "CpuMwdt1",
    0x12: "SysSuperWdt",
    0x13: "SysClkGlitch",
    0x14: "CoreEfuseCrc",
    0x15: "CoreUsbUart",
    0x16: "CoreUsbJtag",
    0x17: "CorePwrGlitch",
}
"""ESP32-S3 `SocResetReason` names, as in the protocol's `errors.md`."""


class Link(Enum):
    """A Rig's Wi-Fi link."""

    OFF = "off"
    """No Wi-Fi credentials, or the radio is off."""
    JOINING = "joining"
    """Joining the network, or waiting to retry."""
    CONNECTED = "connected"


class AddressMode(Enum):
    """How a Rig is set to take its IPv4 address on the network."""

    DHCP = "dhcp"
    STATIC = "static"


_LINKS = (Link.OFF, Link.JOINING, Link.CONNECTED)
_ADDRESS_MODES = (AddressMode.DHCP, AddressMode.STATIC)


@dataclass(frozen=True)
class Status:
    """A Rig's health since boot, its Lock and its network, from `rig.status()`.

    Counters wrap at 2**32. The Wi-Fi passphrase is never reported.
    """

    uptime: timedelta
    """Time since the Rig booted."""
    reset_reason: str
    """Why the Rig last reset, such as `ChipPowerOn` or `CoreSw`.

    `unknown` if the Rig couldn't tell, or `unknown (0x2A)` for a reason this itch-py can't name.
    """
    last_panic: str | None
    """Where the previous boot panicked, such as `src/main.rs:88:5`, or `None`."""
    crc_failures: int
    """Frames dropped for a bad CRC."""
    oversized_frames: int
    """Frames dropped for being over 1024 bytes."""
    malformed_frames: int
    """Payloads dropped for being too short to answer."""
    dropped_logs: int
    """Rig logs dropped because the client didn't keep up."""
    expander_faults: int
    """Times the Channel expander was found faulty and re-initialised."""
    usb_tx_dropped: int
    """Frames the Rig cut short because the USB host stopped reading."""
    holder: str | None
    """Who holds the Rig's Lock, such as `qa@bench-pc`, or `None` if it's unlocked."""
    wifi_configured: bool
    """Whether the Rig has Wi-Fi credentials. Without them it works over USB alone."""
    ssid: str | None
    """The Wi-Fi network the credentials are for, or `None`."""
    link: Link
    """Whether the Rig is on the Wi-Fi network."""
    current_address: IPv4Address | None
    """The Rig's address on the network while connected, or `None`."""
    address_mode: AddressMode
    """How the Rig is set to take its address, whether or not it's connected."""
    static_address: IPv4Interface | None
    """The static address with its prefix, such as `192.0.2.10/24`, or `None` for DHCP."""
    gateway: IPv4Address | None
    """The static gateway, or `None` for DHCP or no gateway."""


def from_reply(reply: _wire.GetStatusReply) -> Status:
    return Status(
        uptime=timedelta(milliseconds=reply.uptime_ms),
        reset_reason=_reset_reason(reply.reset_reason),
        last_panic=reply.last_panic or None,
        crc_failures=reply.crc_failures,
        oversized_frames=reply.oversized_frames,
        malformed_frames=reply.malformed_frames,
        dropped_logs=reply.dropped_logs,
        expander_faults=reply.expander_faults,
        usb_tx_dropped=reply.usb_tx_dropped,
        holder=reply.holder or None,
        wifi_configured=reply.wifi_configured,
        ssid=reply.ssid or None,
        link=_LINKS[reply.link],
        current_address=_address(reply.current_address),
        address_mode=_ADDRESS_MODES[reply.mode],
        static_address=(
            IPv4Interface((reply.address, reply.prefix))
            if reply.mode == _wire.ADDRESS_STATIC
            else None
        ),
        gateway=_address(reply.gateway),
    )


def _address(address: bytes) -> IPv4Address | None:
    """`None` for the zero address."""
    return IPv4Address(address) if any(address) else None


def _reset_reason(code: int) -> str:
    if code == 0:
        return "unknown"
    return _RESET_REASONS.get(code, f"unknown (0x{code:02X})")
