"""Provisioning a Rig's network: `rig.set_wifi()`, `rig.set_address()` and their CLI commands."""

import dataclasses
import getpass
import io
import logging
import sys
from collections.abc import Callable, Iterator
from datetime import timedelta
from ipaddress import IPv4Address, IPv4Interface

import pytest
from conftest import RunningSim
from scripted_rig import ACME_HELLO, HangUp, ScriptedRig, after_connecting

from itch import (
    AddressMode,
    DisconnectedError,
    Link,
    LockedError,
    Rig,
    Status,
    StorageFaultError,
    _connection,
)
from itch._cli import main
from itch._wire import (
    Hello,
    Lock,
    LockReply,
    Message,
    OkResponse,
    ReleaseLock,
    Request,
    SetAddress,
    SetAddressReply,
    SetLogLevel,
    SetLogLevelReply,
    SetWifi,
    SetWifiReply,
)

SSID, PASSPHRASE = "ExampleRigNet", "example-passphrase"

HELPERS: dict[str, Callable[[Rig], None]] = {
    "set_wifi": lambda rig: rig.set_wifi(SSID, PASSPHRASE),
    "clear_wifi": Rig.clear_wifi,
    "set_address": lambda rig: rig.set_address(IPv4Interface("192.0.2.10/24")),
    "use_dhcp": Rig.use_dhcp,
}
"""Every provisioning helper, called with valid settings."""


def settings(status: Status) -> Status:
    """`status` without its uptime, which changes between reads."""
    return dataclasses.replace(status, uptime=timedelta(0))


def test_wifi_credentials_connect_the_link_and_clearing_them_turns_it_off(
    own_sim: RunningSim,
) -> None:
    with Rig.connect(own_sim.url) as rig:
        rig.set_wifi(SSID, PASSPHRASE)
        joined = rig.status()
        rig.clear_wifi()
        cleared = rig.status()
    assert (joined.wifi_configured, joined.ssid, joined.link) == (True, SSID, Link.CONNECTED)
    assert (cleared.wifi_configured, cleared.ssid, cleared.link) == (False, None, Link.OFF)


def test_a_static_address_shows_in_status_and_dhcp_reverts_it(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url) as rig:
        rig.set_wifi(SSID, PASSPHRASE)
        rig.set_address(IPv4Interface("192.0.2.10/24"), gateway=IPv4Address("192.0.2.1"))
        static = rig.status()
        rig.use_dhcp()
        dhcp = rig.status()
    assert (static.address_mode, static.static_address, static.gateway) == (
        AddressMode.STATIC,
        IPv4Interface("192.0.2.10/24"),
        IPv4Address("192.0.2.1"),
    )
    assert static.current_address == IPv4Address("192.0.2.10")
    assert (dhcp.address_mode, dhcp.static_address, dhcp.gateway) == (AddressMode.DHCP, None, None)
    assert dhcp.current_address == IPv4Address("127.0.0.1")  # The sim's bound address.


def test_a_static_address_without_a_gateway_has_none(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url) as rig:
        rig.set_address(IPv4Interface("192.0.2.10/24"))
        status = rig.status()
    assert (status.static_address, status.gateway) == (IPv4Interface("192.0.2.10/24"), None)


@pytest.mark.parametrize("helper", HELPERS.values(), ids=HELPERS.keys())
def test_a_storage_fault_raises_and_keeps_the_old_setting(helper: Callable[[Rig], None]) -> None:
    with RunningSim("--storage-fault") as sim, Rig.connect(sim.url) as rig:
        before = settings(rig.status())
        with pytest.raises(StorageFaultError, match="couldn't save"):
            helper(rig)
        assert settings(rig.status()) == before


@pytest.mark.parametrize("helper", HELPERS.values(), ids=HELPERS.keys())
def test_another_holders_lock_refuses_each_helper(
    own_sim: RunningSim, helper: Callable[[Rig], None]
) -> None:
    with (
        Rig.connect(own_sim.url, holder="alice"),
        Rig.connect(own_sim.url, holder="bob", lock=False) as bob,
    ):
        before = settings(bob.status())
        with pytest.raises(LockedError, match="Locked by alice"):
            helper(bob)
        assert settings(bob.status()) == before


INVALID: dict[str, tuple[Callable[[Rig], None], str]] = {
    "empty SSID": (lambda rig: rig.set_wifi("", PASSPHRASE), "SSID '' is 0 bytes"),
    "33-byte SSID": (lambda rig: rig.set_wifi("é" * 16 + "x", PASSPHRASE), "is 33 bytes"),
    "7-byte passphrase": (lambda rig: rig.set_wifi(SSID, "example"), "passphrase is 7 bytes"),
    "64-byte passphrase": (lambda rig: rig.set_wifi(SSID, "p" * 64), "passphrase is 64 bytes"),
    "zero address": (
        lambda rig: rig.set_address(IPv4Interface("0.0.0.0/24")),
        "0.0.0.0 can't be the Rig's address",
    ),
    "broadcast address": (
        lambda rig: rig.set_address(IPv4Interface("255.255.255.255/32")),
        "255.255.255.255 can't be the Rig's address",
    ),
    "multicast address": (
        lambda rig: rig.set_address(IPv4Interface("224.0.0.251/24")),
        "224.0.0.251 can't be the Rig's address",
    ),
    "prefix 0": (lambda rig: rig.set_address(IPv4Interface("192.0.2.10/0")), "prefix /0"),
    "broadcast gateway": (
        lambda rig: rig.set_address(
            IPv4Interface("192.0.2.10/24"), gateway=IPv4Address("255.255.255.255")
        ),
        "255.255.255.255 can't be the gateway",
    ),
    "multicast gateway": (
        lambda rig: rig.set_address(
            IPv4Interface("192.0.2.10/24"), gateway=IPv4Address("239.0.0.1")
        ),
        "239.0.0.1 can't be the gateway",
    ),
}


@pytest.mark.parametrize(("helper", "message"), INVALID.values(), ids=INVALID.keys())
def test_invalid_settings_raise_value_error_without_sending(
    helper: Callable[[Rig], None], message: str
) -> None:
    with after_connecting(lambda request: []) as peer:
        with Rig.connect(peer.url) as rig, pytest.raises(ValueError, match=message):
            helper(rig)
        assert peer.closed.wait(2)
    assert [r for r in peer.requests if isinstance(r.body, SetWifi | SetAddress)] == []


def granting_network_changes(request: Request) -> Iterator[Message]:
    """Grants `SetWifi` and `SetAddress`, staying silent to anything else."""
    match request.body:
        case SetWifi():
            yield OkResponse(request.request_id, SetWifiReply())
        case SetAddress():
            yield OkResponse(request.request_id, SetAddressReply())
        case _:
            pass


def dropping_after_network_changes(request: Request) -> Iterator[Message]:
    """Grants `SetWifi` and `SetAddress`, then closes the connection as a Rig on Wi-Fi may."""
    yield from granting_network_changes(request)
    raise HangUp


@pytest.mark.parametrize("helper", HELPERS.values(), ids=HELPERS.keys())
def test_a_drop_after_a_network_change_succeeds_then_says_to_reconnect(
    helper: Callable[[Rig], None], caplog: pytest.LogCaptureFixture
) -> None:
    with after_connecting(dropping_after_network_changes) as peer:
        rig = Rig.connect(peer.url)
        helper(rig)
        assert peer.closed.wait(2)
        with pytest.raises(DisconnectedError, match="reconnect after the network change"):
            rig.get_channels()
        with caplog.at_level(logging.DEBUG, logger="itch"):
            rig.close()
    assert caplog.records == []


def test_a_rig_silent_after_a_network_change_has_disconnected(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(_connection, "REQUEST_TIMEOUT", 0.2)
    with after_connecting(granting_network_changes) as peer:
        rig = Rig.connect(peer.url)
        rig.set_address(IPv4Interface("192.0.2.10/24"))
        with pytest.raises(DisconnectedError, match="reconnect after the network change"):
            rig.get_channels()
        with caplog.at_level(logging.DEBUG, logger="itch"):
            rig.close()
    assert caplog.records == []


def test_closing_a_rig_silent_after_a_network_change_tries_to_release_once_quietly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(_connection, "REQUEST_TIMEOUT", 0.2)
    moved = False

    def moving_after_the_change(request: Request) -> list[Message]:
        nonlocal moved
        if moved:  # The Rig is at its new address now.
            return []
        match request.body:
            case Hello():
                return [OkResponse(request.request_id, ACME_HELLO)]
            case SetLogLevel():
                return [OkResponse(request.request_id, SetLogLevelReply())]
            case Lock():
                return [OkResponse(request.request_id, LockReply())]
            case _:
                moved = True
                return [OkResponse(request.request_id, SetAddressReply())]

    with ScriptedRig(moving_after_the_change) as peer:
        rig = Rig.connect(peer.url, holder="alice")
        rig.set_address(IPv4Interface("192.0.2.10/24"))
        with caplog.at_level(logging.DEBUG, logger="itch"):
            rig.close()
        assert peer.closed.wait(2)
    assert caplog.records == []
    assert [r.body for r in peer.requests if isinstance(r.body, ReleaseLock)] == [
        ReleaseLock("alice")
    ]


def test_itch_wifi_set_asks_for_the_passphrase_and_wifi_clear_forgets_it(
    own_sim: RunningSim, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompts: list[str] = []

    def typing_the_passphrase(prompt: str) -> str:
        prompts.append(prompt)
        return PASSPHRASE

    monkeypatch.setattr(getpass, "getpass", typing_the_passphrase)
    assert main(["wifi", "set", own_sim.url, SSID]) == 0
    assert prompts == [f"Passphrase for {SSID}: "]
    assert "itch-514D01 joins ExampleRigNet" in capsys.readouterr().out
    with Rig.connect(own_sim.url, lock=False) as rig:
        assert (rig.status().ssid, rig.status().holder) == (SSID, None)
    assert main(["wifi", "clear", own_sim.url]) == 0
    assert "itch-514D01 has no Wi-Fi" in capsys.readouterr().out
    with Rig.connect(own_sim.url, lock=False) as rig:
        assert (rig.status().wifi_configured, rig.status().holder) == (False, None)


def test_itch_wifi_set_reads_the_passphrase_from_stdin(
    own_sim: RunningSim, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{PASSPHRASE}\n"))
    assert main(["wifi", "set", "--passphrase-stdin", own_sim.url, SSID]) == 0
    with Rig.connect(own_sim.url, lock=False) as rig:
        assert rig.status().ssid == SSID


def test_itch_wifi_set_refuses_a_short_passphrase_from_stdin(
    own_sim: RunningSim, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("example\n"))
    assert main(["wifi", "set", "--passphrase-stdin", own_sim.url, SSID]) == 1
    assert "passphrase is 7 bytes" in capsys.readouterr().err


def test_itch_address_static_sets_the_address_and_address_dhcp_reverts_it(
    own_sim: RunningSim, capsys: pytest.CaptureFixture[str]
) -> None:
    command = ["address", "static", own_sim.url, "192.0.2.10/24", "--gateway", "192.0.2.1"]
    assert main(command) == 0
    assert "itch-514D01 uses 192.0.2.10/24" in capsys.readouterr().out
    with Rig.connect(own_sim.url, lock=False) as rig:
        status = rig.status()
    assert (status.static_address, status.gateway, status.holder) == (
        IPv4Interface("192.0.2.10/24"),
        IPv4Address("192.0.2.1"),
        None,
    )
    assert main(["address", "dhcp", own_sim.url]) == 0
    assert "itch-514D01 takes its address from DHCP" in capsys.readouterr().out
    with Rig.connect(own_sim.url, lock=False) as rig:
        assert (rig.status().address_mode, rig.status().holder) == (AddressMode.DHCP, None)


def test_itch_address_static_refuses_a_multicast_address(
    own_sim: RunningSim, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["address", "static", own_sim.url, "224.0.0.251/24"]) == 1
    assert "224.0.0.251 can't be the Rig's address" in capsys.readouterr().err


def test_itch_address_static_help_says_to_fix_a_wrong_address_over_usb(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["address", "static", "--help"])
    assert "fix it over USB" in capsys.readouterr().out


def test_a_provisioning_command_fails_while_another_holder_has_the_lock(
    own_sim: RunningSim, capsys: pytest.CaptureFixture[str]
) -> None:
    with Rig.connect(own_sim.url, holder="alice"):
        assert main(["address", "dhcp", own_sim.url]) == 1
    assert "Locked by alice" in capsys.readouterr().err
