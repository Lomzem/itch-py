"""A stubbed network for discovery: the mDNS advertisements a browse finds, without multicast."""

from __future__ import annotations

from urllib.parse import urlsplit

from itch._mdns import Advert


class FakeNetwork:
    def __init__(self) -> None:
        self.adverts: list[Advert] = []
        self.browses: list[float] = []
        """The timeout of each browse, in seconds, oldest first."""

    def advertise(
        self, instance: str, hardware_id: str, url: str = "tcp://192.0.2.10:7878"
    ) -> None:
        """Advertises a Rig as mDNS instance `instance`, reachable at `url`."""
        where = urlsplit(url)
        assert where.hostname is not None
        assert where.port is not None
        self.adverts.append(Advert(instance, where.hostname, where.port, hardware_id))

    def __call__(self, timeout: float) -> list[Advert]:
        self.browses.append(timeout)
        return list(self.adverts)
