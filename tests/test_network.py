"""Finding Rigs on the network by their mDNS advertisements, against a stubbed browse."""

import contextlib
import dataclasses
import time

import pytest
from conftest import RunningSim
from fake_bench import FakeBench
from fake_network import FakeNetwork
from scripted_rig import ACME_HELLO, answering
from zeroconf import ServiceInfo

from itch import (
    AmbiguousRigError,
    ItchError,
    Rig,
    RigInfo,
    RigNotFoundError,
    _mdns,
    list_rigs,
)
from itch._cli import main
from itch._wire import HelloReply

HW = "60:55:F9:C0:27:18"


@pytest.mark.parametrize("name", ["BENCH3", HW.lower()])
def test_a_label_or_hardware_id_connects_to_the_rig_advertising_it(
    network: FakeNetwork, name: str
) -> None:
    network.advertise("bench4", "60:55:F9:C0:27:19")
    with answering(ACME_HELLO) as peer:
        network.advertise("bench3", HW, peer.url)
        with Rig.connect(name) as rig:
            assert (rig.label, rig.hardware_id) == ("bench3", HW)


@pytest.mark.parametrize(
    ("label", "instance"),
    [
        pytest.param("b" * 64, "b" * 63, id="ascii"),
        pytest.param("b" * 62 + "é", "b" * 62, id="cut-before-a-two-byte-character"),
    ],
)
def test_a_64_byte_label_matches_the_63_byte_instance_it_advertises(
    network: FakeNetwork, label: str, instance: str
) -> None:
    with answering(dataclasses.replace(ACME_HELLO, label=label)) as peer:
        network.advertise(instance, HW, peer.url)
        with Rig.connect(label) as rig:
            assert rig.label == label


def test_two_rigs_advertising_a_label_are_ambiguous_and_neither_is_connected(
    network: FakeNetwork,
) -> None:
    network.advertise("bench3", HW, "tcp://192.0.2.10:7878")
    network.advertise("Bench3", "60:55:F9:C0:27:19", "tcp://192.0.2.11:7878")
    with pytest.raises(AmbiguousRigError) as raised:
        Rig.connect("bench3")
    assert str(raised.value).splitlines() == [
        "2 Rigs on the network are labelled 'bench3'; pass Rig.connect() the Hardware ID or "
        "tcp://host:port of one:",
        "  PORT                   HARDWARE ID        LABEL   FIRMWARE",
        "  tcp://192.0.2.10:7878  60:55:F9:C0:27:18  bench3",
        "  tcp://192.0.2.11:7878  60:55:F9:C0:27:19  Bench3",
    ]


def test_one_rig_answering_twice_is_not_ambiguous(network: FakeNetwork) -> None:
    with answering(ACME_HELLO) as peer:
        network.advertise("bench3", HW, peer.url)
        network.advertise("bench3", HW.lower(), peer.url)
        with Rig.connect("bench3") as rig:
            assert rig.hardware_id == HW


def test_a_rig_plugged_in_over_usb_wins_without_browsing(
    network: FakeNetwork, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeBench(monkeypatch).rig("/dev/ttyACM0", "60:55:F9:C0:27:19", "bench3")
    network.advertise("bench3", HW)
    with Rig.connect("bench3") as rig:
        assert rig.hardware_id == "60:55:F9:C0:27:19"
    assert network.browses == []


@pytest.mark.parametrize(
    ("hello", "name", "error", "message"),
    [
        pytest.param(
            dataclasses.replace(ACME_HELLO, label="b" * 63 + "x"),
            "b" * 63 + "y",
            RigNotFoundError,
            "Rig 'b{63}y' not found: the Rig advertising it at tcp://.* is labelled 'b{63}x'",
            id="label",
        ),
        pytest.param(
            dataclasses.replace(ACME_HELLO, hardware_id=bytes.fromhex("6055f9c02719")),
            "bench3",
            ItchError,
            f"says its Hardware ID is 60:55:F9:C0:27:19, but it advertises {HW}",
            id="hardware-id",
        ),
    ],
)
def test_a_rig_whose_hello_contradicts_its_advert_is_refused_and_closed(
    network: FakeNetwork, hello: HelloReply, name: str, error: type[ItchError], message: str
) -> None:
    with answering(hello) as peer:
        network.advertise(_mdns.advertised(name), HW, peer.url)
        with pytest.raises(error, match=message):
            Rig.connect(name)
        assert peer.closed.wait(2)


def test_a_name_nothing_advertises_is_not_found_after_the_browse_timeout(
    network: FakeNetwork,
) -> None:
    network.advertise("bench4", HW)
    with pytest.raises(RigNotFoundError) as raised:
        Rig.connect("bench3", browse_timeout=0.5)
    assert network.browses == [0.5]
    assert str(raised.value).splitlines() == [
        "Rig 'bench3' not found over USB or on the network. Rigs found:",
        "  PORT                   HARDWARE ID        LABEL   FIRMWARE",
        "  tcp://192.0.2.10:7878  60:55:F9:C0:27:18  bench4",
    ]


def test_with_no_rig_anywhere_the_default_browse_timeout_is_3_seconds() -> None:
    with pytest.raises(
        RigNotFoundError,
        match=r"^Rig 'bench3' not found: no Rig is plugged in, and none answered on the network "
        r"within 3 s\.$",
    ):
        Rig.connect("bench3")


def test_list_rigs_adds_network_rigs_once_each_after_those_plugged_in_over_usb(
    network: FakeNetwork, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeBench(monkeypatch).rig("/dev/ttyACM0", HW, "bench3")
    network.advertise("bench3", HW.lower(), "tcp://192.0.2.10:7878")
    network.advertise("bench4", "60:55:F9:C0:27:19", "tcp://192.0.2.11:7878")
    network.advertise("bench4", "60:55:F9:C0:27:19", "tcp://192.0.2.11:7878")
    assert list_rigs(browse_timeout=0.5) == [
        RigInfo("/dev/ttyACM0", HW, "bench3", "1.0.0"),
        RigInfo("tcp://192.0.2.11:7878", "60:55:F9:C0:27:19", "bench4", None, transport="tcp"),
    ]
    assert network.browses == [0.5]
    assert main(["list"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "PORT                   HARDWARE ID        LABEL   FIRMWARE",
        "/dev/ttyACM0           60:55:F9:C0:27:18  bench3  1.0.0",
        "tcp://192.0.2.11:7878  60:55:F9:C0:27:19  bench4",
    ]


def test_a_tcp_address_connects_without_browsing(network: FakeNetwork) -> None:
    with answering(ACME_HELLO) as peer, Rig.connect(peer.url):
        pass
    assert network.browses == []


def test_a_fifth_network_connection_fails_at_once_naming_the_likely_limit(
    own_sim: RunningSim,
) -> None:
    with contextlib.ExitStack() as rigs:
        for _ in range(4):
            rigs.enter_context(Rig.connect(own_sim.url))
        started = time.monotonic()
        with pytest.raises(ItchError) as raised:
            Rig.connect(own_sim.url)
        assert time.monotonic() - started < 1
    assert str(raised.value) == (
        f"Rig at {own_sim.url} closed the connection before replying to Hello; it may already "
        "have 4 network connections."
    )


@pytest.mark.parametrize(
    ("txt", "advert"),
    [
        pytest.param(
            {"hwid": "60:55:f9:c0:27:18"},
            _mdns.Advert("bench.3 é", "192.0.2.10", 7878, HW),
            id="valid",
        ),
        pytest.param({}, None, id="no-hwid"),
        pytest.param({"hwid": "6055F9C02718"}, None, id="malformed-hwid"),
    ],
)
def test_a_resolved_advertisement_keeps_a_dotted_label_and_needs_a_valid_hwid(
    txt: dict[str, str], advert: _mdns.Advert | None
) -> None:
    info = ServiceInfo(
        _mdns.SERVICE,
        f"bench.3 é.{_mdns.SERVICE}",
        port=7878,
        properties=txt,
        server="itch-c02718.local.",
        parsed_addresses=["192.0.2.10"],
    )
    assert _mdns.to_advert(info) == advert
