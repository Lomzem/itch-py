"""The USB transport through real pySerial, to `itch-sim` over a pseudo-terminal (Linux)."""

from __future__ import annotations

import os
import select
import socket
import sys
import threading
from collections.abc import Iterator

import pytest
from conftest import RunningSim
from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

from itch import Rig, RigNotFoundError

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
    while True:
        ready, _, _ = select.select([controller, sim, stop], [], [])
        if stop in ready:
            return
        if controller in ready:
            sim.sendall(os.read(controller, 4096))
        if sim in ready:
            os.write(controller, sim.recv(4096))


def test_talks_to_a_rig_through_pyserial(pty_rig: str) -> None:
    with Rig.connect() as rig:
        assert rig.hardware_id == SIM_HARDWARE_ID
        with rig.session():
            rig.set_channel(3, "on")
        assert rig.get_channel(3) == "on"


def test_a_port_another_itch_py_has_open_is_in_use(pty_rig: str) -> None:
    with Rig.connect(pty_rig), pytest.raises(RigNotFoundError, match="in use by another program"):
        Rig.connect(SIM_HARDWARE_ID)
    Rig.connect(pty_rig).close()
