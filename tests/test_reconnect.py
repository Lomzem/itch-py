"""Script exit and reconnect release Locks without changing Channels."""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from acme_widget import AcmeWidget
from conftest import RunningSim
from fake_network import FakeNetwork

from itch import DisconnectedError, Rig

REPLACED = "connected to the same Rig again"

DUT_USES: dict[str, Callable[[AcmeWidget], object]] = {
    "Channel-write": lambda dut: dut.set(1),
    "Channel-read": lambda dut: dut.get_all(),
    "Field-write": lambda dut: dut.mode.set("night"),
    "Field-read": lambda dut: dut.mode.get(),
}


@pytest.mark.parametrize("uncaught", [False, True], ids=["normal-exit", "uncaught-exception"])
@pytest.mark.parametrize("retained", [True, False], ids=["retained-Rig", "dropped-Rig"])
def test_interpreter_exit_releases_the_lock_without_changing_channels(
    own_sim: RunningSim, uncaught: bool, retained: bool
) -> None:
    connect = f'Rig.connect({own_sim.url!r}, holder="alice")'
    script = "from itch import Rig\n"
    if retained:
        script += f"rig = {connect}\nrig.apply(0x8011)\n"
    else:
        script += f"{connect}.set(1)\n"
    if uncaught:
        script += 'raise RuntimeError("the QA script failed")\n'
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    if uncaught:
        assert result.returncode != 0
        assert result.stderr.startswith("Traceback (most recent call last):")
        assert result.stderr.splitlines()[-1] == "RuntimeError: the QA script failed"
        assert "ItchError" not in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
    with Rig.connect(own_sim.url, holder="bob", lock=False) as observer:
        assert observer.get_all() == (0x8011 if retained else 0x0001)
        assert observer.status().holder is None


def test_exit_releases_other_rigs_when_a_cleanup_warning_cannot_be_logged(
    own_sim: RunningSim, tmp_path: Path
) -> None:
    with RunningSim() as second:
        script = f"""
import logging
import sys
from itch import Rig
alice = Rig.connect({own_sim.url!r}, holder="alice")
carol = Rig.connect({second.url!r}, holder="carol")
alice.set(1)
carol.set(2)
logging.getLogger("itch").addHandler(
    logging.FileHandler({str(tmp_path / "missing" / "cleanup.log")!r}, delay=True)
)
print("locked", flush=True)
assert sys.stdin.readline().strip() == "exit"
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
                assert other.stdout.readline().strip() == "locked"
                with Rig.connect(own_sim.url, holder="bob", take_over=True) as bob:
                    _, stderr = other.communicate("exit\n", timeout=10)
                    assert other.returncode == 0, stderr
                    assert bob.status().holder == "bob"
                    assert bob.get_all() == 0x0001
                    with Rig.connect(second.url, lock=False) as observer:
                        assert observer.status().holder is None
                        assert observer.get_all() == 0x0002
                    assert stderr == ""
            finally:
                other.communicate(timeout=10)


@pytest.mark.parametrize("via", ["address", "localhost", "mdns-label", "mdns-hardware-id"])
def test_reconnect_releases_the_older_holders_lock_without_changing_channels(
    own_sim: RunningSim, network: FakeNetwork, via: str
) -> None:
    with Rig.connect(own_sim.url, holder="alice") as old:
        old.apply(0x8011)
        name = own_sim.url
        if via == "localhost":
            port = own_sim.url.rsplit(":", 1)[1]
            name = f"tcp://localhost:{port}"
        elif via.startswith("mdns-"):
            network.advertise(old.label, old.hardware_id, own_sim.url)
            name = old.label if via == "mdns-label" else old.hardware_id
        with Rig.connect(name, holder="bob") as new:
            assert new.status().holder == "bob"
            assert new.get_all() == 0x8011
            with pytest.raises(DisconnectedError, match=REPLACED):
                old.set(1)
            old.disconnect()  # A stale object's cleanup must not release Bob's Lock.
            assert new.status().holder == "bob"
            assert new.get_all() == 0x8011


@pytest.mark.parametrize("use", DUT_USES.values(), ids=DUT_USES.keys())
def test_a_replaced_dut_explains_why_it_was_disconnected(
    own_sim: RunningSim, use: Callable[[AcmeWidget], object]
) -> None:
    with Rig.connect(own_sim.url, AcmeWidget, holder="alice") as dut:
        dut.apply(0x800B)
        with Rig.connect(own_sim.url, holder="alice") as new:
            with pytest.raises(DisconnectedError, match=REPLACED):
                use(dut)
            dut.disconnect()
            assert new.status().holder == "alice"
            assert new.get_all() == 0x800B


def test_an_explicit_disconnect_keeps_its_reason_after_connecting_again(
    own_sim: RunningSim,
) -> None:
    old = Rig.connect(own_sim.url, holder="alice")
    old.disconnect()
    with Rig.connect(own_sim.url, holder="bob"):
        with pytest.raises(DisconnectedError, match="was disconnected by this script"):
            old.get_all()
        old.disconnect()
