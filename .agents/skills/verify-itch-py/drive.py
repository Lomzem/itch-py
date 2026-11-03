#!/usr/bin/env python3
"""Drive public itch user journeys against an owned, pinned-release simulator."""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "docs")]

from conftest import RunningSim  # noqa: E402
from itch_release import TAG, fetch  # noqa: E402
from profile_template import AcmeWidget  # noqa: E402

import itch  # noqa: E402
from itch import BatchConflictError, Rig, ch  # noqa: E402


def doctor(url: str) -> None:
    assert itch.__file__ is not None
    source = Path(itch.__file__).resolve()
    assert source == ROOT / "src/itch/__init__.py", f"Imported another checkout: {source}"
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10
    ).strip()
    print("SOURCE", source, "CHECKOUT", revision)
    print(f"DOCTOR Rig.connect({url!r}, lock=False); status(); get_all()", flush=True)
    with Rig.connect(url, lock=False) as rig:
        status, state = rig.status(), rig.get_all()
        print(rig.label, rig.hardware_id, rig.firmware_version, status, state)
        assert rig.hardware_id == "02:00:00:51:4D:01"
        assert rig.firmware_version == TAG.removeprefix("v")
        assert status.holder is None
        assert state == 0


def channels(url: str) -> None:
    with Rig.connect(url) as rig:
        print("ACTION rig.set(1, 5); rig.clear(1); rig.write(set=[2], clear=[5])")
        rig.set(1, 5)
        assert rig.get_all() == 0x0011
        rig.clear(1)
        assert rig.get_all() == 0x0010
        rig.write(set=[2], clear=[5])
        assert rig.get_all() == 0x0002
        print("ACTION rig.apply(ch(9), mask=ch(9, 10)); rig.get(9); rig.get_all()")
        rig.apply(ch(9), mask=ch(9, 10))
        assert rig.get(9) is True
        print("RESULT", rig.get_all())
        assert rig.get_all() == 0x0102
    with Rig.connect(url, lock=False) as observer:
        print("RECONNECT", observer.get_all(), "holder", observer.status().holder)
        assert observer.get_all() == 0x0102
        assert observer.status().holder is None


def profiles(url: str) -> None:
    with Rig.connect(url, AcmeWidget) as dut:
        print("ACTION dut.resolution.set('1080p'); dut.apply(resolution='720p', standby='enabled')")
        dut.resolution.set("1080p")
        assert dut.resolution.get() == "1080p"
        assert dut.get_all() == 0x0002
        dut.apply(resolution="720p", standby="enabled")
        print("RESULT", dut.resolution.get(), dut.standby.get(), dut.get_all())
        assert dut.get_all() == 0x0041
        print("ACTION dut.apply(picture='bars', tone='silent') -> BatchConflictError")
        try:
            dut.apply(picture="bars", tone="silent")
        except BatchConflictError as error:
            print("REFUSED", error)
        else:
            raise AssertionError("Conflicting Fields were accepted")
        assert dut.get_all() == 0x0041
    with Rig.connect(url, AcmeWidget, lock=False) as observer:
        assert observer.resolution.get() == "720p"
        assert observer.standby.get() == "enabled"
        print("RECONNECT", observer.resolution.get(), observer.standby.get())


def locks(url: str) -> None:
    print("ACTION connect holder='verification-alice'; separate process connects as Bob")
    with Rig.connect(url, holder="verification-alice") as alice:
        alice.set(1)
        script = """
import sys
from itch import LockedError, Rig
try:
    Rig.connect(sys.argv[1], holder="verification-bob")
except LockedError as error:
    print("REFUSED", error)
else:
    raise AssertionError("A different Holder acquired the Lock")
with Rig.connect(sys.argv[1], holder="verification-bob", lock=False) as bob:
    assert bob.get_all() == 0x0001
    assert bob.status().holder == "verification-alice"
    print("OBSERVER", bob.get_all(), "holder", bob.status().holder)
"""
        result = subprocess.run(
            [sys.executable, "-c", script, url],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        print("STDOUT", result.stdout, "STDERR", result.stderr, "EXIT", result.returncode)
        assert result.returncode == 0
    with Rig.connect(url, holder="verification-bob") as bob:
        assert bob.status().holder == "verification-bob"
        assert bob.get_all() == 0x0001
        print("AFTER RELEASE", bob.get_all(), "holder", bob.status().holder)


def labels(url: str) -> None:
    print("ACTION rig.set_label('verification-bench')")
    with Rig.connect(url) as rig:
        rig.set_label("verification-bench")
        assert rig.label == "verification-bench"
    with Rig.connect(url, lock=False) as observer:
        print("PYTHON RECONNECT", observer.label, "holder", observer.status().holder)
        assert observer.label == "verification-bench"
        assert observer.status().holder is None
    console = shutil.which("itch")
    assert console is not None, "The installed itch console command is missing from PATH"
    for entry, label in (
        ([sys.executable, "-m", "itch"], "verification-module"),
        ([console], "verification-console"),
    ):
        command = [*entry, "label", url, label]
        print("ACTION", command)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
        print("STDOUT", result.stdout, "STDERR", result.stderr, "EXIT", result.returncode)
        assert result.returncode == 0
        assert label in result.stdout
        with Rig.connect(url, lock=False) as observer:
            print("RECONNECT", observer.label, "holder", observer.status().holder)
            assert observer.label == label
            assert observer.status().holder is None


def main() -> None:
    journeys = {"channels": channels, "profiles": profiles, "locks": locks, "labels": labels}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature", choices=["doctor", *journeys])
    args = parser.parse_args()
    evidence = ROOT / ".scratch/repo-improvements/verification-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=f"{args.feature}-", dir=evidence))
    print(f"Evidence: {run / 'transcript.txt'}", flush=True)
    with (
        (run / "transcript.txt").open("w", encoding="utf-8", buffering=1) as transcript,
        contextlib.redirect_stdout(transcript),
        contextlib.redirect_stderr(transcript),
    ):
        print("itch", importlib.metadata.version("itch"), "simulator release", TAG)
        try:
            release = fetch()
            print("LAUNCH", release.sim, "(manifest SHA-256 verified)")
            try:
                with RunningSim(command=[release.sim]) as sim:
                    print("READY", sim.url)
                    doctor(sim.url)
                    if args.feature != "doctor":
                        journeys[args.feature](sim.url)
            finally:
                print("CLEANUP simulator context exited; evidence retained")
            print("PASS", args.feature)
        except BaseException:
            traceback.print_exc()
            raise


if __name__ == "__main__":
    main()
