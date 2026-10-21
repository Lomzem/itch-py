"""Renaming a Rig with `rig.set_label()` and `itch label`."""

import pytest
from conftest import RunningSim

from itch import Rig, StorageFaultError
from itch._cli import main

SIM_DEFAULT = "itch-514D01"
"""The sim's default label: `itch-` plus the last three bytes of its Hardware ID."""


def test_a_new_label_shows_on_the_rig_and_in_hello(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url) as rig:
        assert rig.label == SIM_DEFAULT
        rig.set_label("bench3")
        assert rig.label == "bench3"
    with Rig.connect(own_sim.url) as rig:
        assert rig.label == "bench3"


def test_an_empty_label_restores_the_default(own_sim: RunningSim) -> None:
    with Rig.connect(own_sim.url) as rig:
        rig.set_label("bench3")
        rig.set_label("")
        assert rig.label == SIM_DEFAULT


def test_a_label_over_64_bytes_is_refused(rig: Rig) -> None:
    with pytest.raises(ValueError, match="65 bytes"):
        rig.set_label("a" * 65)
    assert rig.label == SIM_DEFAULT


def test_a_storage_fault_raises_and_keeps_the_label() -> None:
    with RunningSim("--storage-fault") as sim, Rig.connect(sim.url) as rig:
        with pytest.raises(StorageFaultError, match="couldn't save"):
            rig.set_label("bench3")
        assert rig.label == SIM_DEFAULT
        with Rig.connect(sim.url) as again:
            assert again.label == SIM_DEFAULT


def test_itch_label_renames_the_rig_and_leaves_it_unlocked(
    own_sim: RunningSim, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["label", own_sim.url, "bench3"]) == 0
    assert "bench3" in capsys.readouterr().out
    with Rig.connect(own_sim.url, lock=False) as rig:
        assert rig.label == "bench3"
        assert rig.status().holder is None


def test_itch_label_reports_an_error_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    with RunningSim("--storage-fault") as sim:
        assert main(["label", sim.url, "bench3"]) == 1
    assert "couldn't save" in capsys.readouterr().err
