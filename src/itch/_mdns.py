"""Finding Rigs on the network by browsing mDNS for their `_itch._tcp` advertisements.

A Rig on Wi-Fi advertises its Label as the instance name, cut to 63 bytes if longer, and its
Hardware ID as TXT `hwid`. Discovery calls `browse`, which tests replace with a fake.
"""

from __future__ import annotations

import dataclasses
import queue
import re
import time
from typing import Protocol

from zeroconf import (
    IPVersion,
    ServiceBrowser,
    ServiceInfo,
    ServiceListener,
    Zeroconf,
    current_time_millis,
)
from zeroconf._cache import DNSCache

# zeroconf leaves its record types out of `__all__`, so import them from where they live. That
# module is private, so pyproject.toml keeps zeroconf below 0.152.
from zeroconf._dns import DNSAddress, DNSService, DNSText

SERVICE = "_itch._tcp.local."

BROWSE_TIMEOUT = 3.0
"""Seconds a lookup or listing browses the network for Rigs, by default."""

_RESOLVE_TIMEOUT = 1.0
"""Seconds to wait for one advertisement's address and TXT, within the browse."""

_HARDWARE_ID = re.compile(r"[0-9A-F]{2}(:[0-9A-F]{2}){5}")


@dataclasses.dataclass(frozen=True)
class Advert:
    """One Rig's mDNS advertisement."""

    instance: str
    """The Rig's Label, cut at a character boundary to 63 bytes if longer."""
    address: str
    """Its IPv4 address, such as `192.0.2.10`."""
    port: int
    hardware_id: str
    """From TXT `hwid`, such as `60:55:F9:C0:27:18`."""

    @property
    def url(self) -> str:
        return f"tcp://{self.address}:{self.port}"


class Browser(Protocol):
    def __call__(self, timeout: float) -> list[Advert]:
        """Every advertisement heard within `timeout` seconds."""
        ...


def advertised(label: str) -> str:
    """The instance name a Rig labelled `label` advertises: at most 63 bytes, as DNS allows."""
    return label.encode()[:63].decode(errors="ignore")


def browse_zeroconf(timeout: float) -> list[Advert]:
    """Browses for the whole of `timeout`, keeping every Rig that answers, not just the first
    per name, each at the address it last announced.

    Two Rigs advertising the same instance name reach zeroconf as one service, which
    `ServiceInfo` resolves to just one of them. So each update reads every record the cache
    holds for the name, and a Rig stays found after another's answer flushes its records. That
    finds both Rigs when both answer within `timeout`, but can't promise to: a lookup still
    checks the Rig's `Hello` after connecting.
    """
    names: queue.Queue[tuple[bool, str]] = queue.Queue()
    found: dict[str, dict[str, Advert]] = {}
    """Each name's Rigs, by Hardware ID."""

    class Listener(ServiceListener):
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            names.put((True, name))

        def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            names.put((True, name))

        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            names.put((False, name))

    deadline = time.monotonic() + timeout
    zc = Zeroconf(ip_version=IPVersion.V4Only)
    try:
        browser = ServiceBrowser(zc, SERVICE, Listener())
        try:
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    present, name = names.get(timeout=remaining)
                except queue.Empty:
                    break
                if not present:
                    found.pop(name, None)  # A goodbye, such as after a rename.
                    continue
                wait = min(_RESOLVE_TIMEOUT, deadline - time.monotonic())
                if wait > 0:  # Asks for any of the Rig's records the cache lacks.
                    ServiceInfo(SERVICE, name).request(zc, wait * 1000)
                for advert in current_adverts(zc.cache, name, current_time_millis()):
                    # Replaces the Rig's old address, if it moved.
                    found.setdefault(name, {})[advert.hardware_id] = advert
        finally:
            browser.cancel()
    finally:
        zc.close()
    return [advert for rigs in found.values() for advert in rigs.values()]


def current_adverts(cache: DNSCache, name: str, now: float) -> list[Advert]:
    """Every Rig whose SRV, TXT and address `cache` holds for service `name` at time `now`, in
    milliseconds on zeroconf's clock, each at the address it announced last.

    Records past their TTL don't count. Nor does an address a Rig has moved from: the cache
    keeps it until it expires, a second after the new one flushes it, or until its TTL runs out
    without a flush, so the address with the most TTL left is the latest. A Rig's SRV names its
    host `itch-` plus its Hardware ID's last three bytes, which pairs it with that Rig's TXT
    when several Rigs answer for one name.
    """
    records = [record for record in cache.entries_with_name(name) if not record.is_expired(now)]
    services = [record for record in records if isinstance(record, DNSService)]
    adverts: set[Advert] = set()
    for text in (record for record in records if isinstance(record, DNSText)):
        for service in services:
            latest = sorted(
                (
                    record
                    for record in cache.entries_with_name(service.server)
                    if isinstance(record, DNSAddress) and not record.is_expired(now)
                ),
                key=lambda record: record.get_remaining_ttl(now),
                reverse=True,
            )
            addresses = [record.address for record in latest]
            info = ServiceInfo(
                SERVICE,
                name,
                port=service.port,
                properties=text.text,
                server=service.server,
                addresses=addresses,
            )
            advert = to_advert(info)
            if advert and (len(services) == 1 or service.server.lower() == _host(advert)):
                adverts.add(advert)
    return list(adverts)


def _host(advert: Advert) -> str:
    return f"itch-{advert.hardware_id[-8:].replace(':', '').lower()}.local."


def to_advert(info: ServiceInfo) -> Advert | None:
    """The advertisement `info` resolved, or `None` without an IPv4 address or a valid `hwid`."""
    addresses = info.parsed_addresses(IPVersion.V4Only)
    hwid = info.properties.get(b"hwid")
    if not addresses or info.port is None or hwid is None:
        return None
    hardware_id = hwid.decode("ascii", errors="replace").upper()
    if not _HARDWARE_ID.fullmatch(hardware_id):
        return None
    return Advert(info.get_name(), addresses[0], info.port, hardware_id)


browse: Browser = browse_zeroconf
