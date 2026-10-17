from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

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


@dataclass(frozen=True)
class Status:
    """A Rig's health since boot, from `rig.status()`. Counters wrap at 2**32."""

    uptime: timedelta
    """Time since the Rig booted."""
    reset_reason: str
    """Why the Rig last reset, such as `ChipPowerOn` or `CoreSw`.

    `unknown` if the Rig couldn't tell, or `unknown (0x2A)` for a reason this itch-py can't name.
    """
    last_panic: str | None
    """Where the previous boot panicked, such as `src/main.rs:88:5`, or `None`."""
    holder: str | None
    """Who holds the Rig's Lease, or `None` if it's free."""
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


def from_reply(reply: _wire.GetStatusReply) -> Status:
    return Status(
        uptime=timedelta(milliseconds=reply.uptime_ms),
        reset_reason=_reset_reason(reply.reset_reason),
        last_panic=reply.last_panic or None,
        holder=reply.holder or None,
        crc_failures=reply.crc_failures,
        oversized_frames=reply.oversized_frames,
        malformed_frames=reply.malformed_frames,
        dropped_logs=reply.dropped_logs,
        expander_faults=reply.expander_faults,
        usb_tx_dropped=reply.usb_tx_dropped,
    )


def _reset_reason(code: int) -> str:
    if code == 0:
        return "unknown"
    return _RESET_REASONS.get(code, f"unknown (0x{code:02X})")
