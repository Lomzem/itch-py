"""The USB transport through real pySerial, to `itch-sim` over a pseudo-terminal (Linux)."""

from __future__ import annotations

import contextlib
import os
import select
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import RunningSim
from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

from itch import (
    DisconnectedError,
    NotRespondingError,
    Rig,
    RigNotFoundError,
    _connection,
    list_rigs,
)

SIM_HARDWARE_ID = "02:00:00:51:4D:01"


@pytest.fixture
def pty_rig(own_sim: RunningSim, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A pty listed as a Rig and wired to the sim. Yields its device path."""
    if sys.platform != "linux":
        pytest.skip("needs a Linux pty")
    import pty

    controller, device = pty.openpty()  # Holding `device` open keeps the pty up between opens.
    host, port = own_sim.url.removeprefix("tcp://").rsplit(":", 1)
    sim = socket.create_connection((host, int(port)))
    stop_read, stop_write = os.pipe()
    relay = threading.Thread(target=_relay, args=(controller, sim, stop_read), daemon=True)
    relay.start()
    path = os.ttyname(device)
    info = ListPortInfo(path, skip_link_detection=True)
    info.vid, info.pid, info.serial_number = 0x303A, 0x1001, SIM_HARDWARE_ID
    monkeypatch.setattr(list_ports, "comports", lambda include_links=False: [info])
    yield path
    os.write(stop_write, b"x")
    relay.join()
    for fd in (controller, device, stop_read, stop_write):
        os.close(fd)
    sim.close()


def _relay(controller: int, sim: socket.socket, stop: int) -> None:
    """Relays bytes between the pty and the sim until stopped or the sim stops."""
    with contextlib.suppress(OSError):  # The sim stopped: the Rig goes silent, as over USB.
        while True:
            ready, _, _ = select.select([controller, sim, stop], [], [])
            if stop in ready:
                return
            if controller in ready:
                sim.sendall(os.read(controller, 4096))
            if sim in ready:
                if not (data := sim.recv(4096)):
                    return
                os.write(controller, data)


def test_talks_to_a_rig_through_pyserial(pty_rig: str) -> None:
    with Rig.connect() as rig:
        assert rig.hardware_id == SIM_HARDWARE_ID
        rig.set(3)
        assert rig.get(3) is True


def test_a_port_another_process_has_open_is_in_use(pty_rig: str) -> None:
    script = f"""
import sys
import serial
with serial.Serial({pty_rig!r}, baudrate=115200, exclusive=True):
    print("port open", flush=True)
    sys.stdin.read()
"""
    with subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as other:
        try:
            assert other.stdout is not None
            assert other.stdout.readline().strip() == "port open"
            with pytest.raises(RigNotFoundError, match="in use by another program"):
                Rig.connect(SIM_HARDWARE_ID)
        finally:
            other.communicate(timeout=10)
        assert other.returncode == 0
    with Rig.connect(pty_rig) as rig:
        assert rig.hardware_id == SIM_HARDWARE_ID


@pytest.mark.parametrize("via", ["device", "symlink", "Hardware-ID", "label", "sole-port"])
def test_usb_reconnect_releases_the_port_before_opening_it_again(
    pty_rig: str, tmp_path: Path, via: str
) -> None:
    with Rig.connect(pty_rig, holder="alice") as old:
        old.apply(0x8011)
        name: str | None = pty_rig
        if via == "symlink":
            link = tmp_path / "rig-port"
            link.symlink_to(pty_rig)
            name = str(link)
        elif via == "Hardware-ID":
            name = SIM_HARDWARE_ID
        elif via == "label":
            name = old.label
        elif via == "sole-port":
            name = None
        with Rig.connect(name, holder="bob") as new:
            assert new.status().holder == "bob"
            assert new.get_all() == 0x8011
            with pytest.raises(DisconnectedError, match="connected to the same Rig again"):
                old.set(1)
            old.disconnect()
            assert new.status().holder == "bob"


def test_listing_an_open_usb_rig_leaves_it_connected_and_in_use(pty_rig: str) -> None:
    with Rig.connect(pty_rig, holder="alice") as rig:
        rig.apply(0x8011)
        [info] = list_rigs()
        assert info.port == pty_rig
        assert info.in_use
        assert rig.status().holder == "alice"
        assert rig.get_all() == 0x8011


def test_over_usb_silence_after_a_network_change_is_unexpected(
    pty_rig: str, own_sim: RunningSim, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_connection, "REQUEST_TIMEOUT", 0.2)
    with Rig.connect(lock=False) as rig:
        rig.set_wifi("ExampleRigNet", "example-passphrase")
        own_sim.stop()
        with pytest.raises(NotRespondingError):
            rig.get_all()
