"""Finding Rigs over USB, against a stubbed port list and a fake `serial.Serial`."""

import dataclasses
import errno
import logging
import sys
from pathlib import Path

import pytest
from fake_bench import FakeBench
from serial.tools.list_ports_common import ListPortInfo

from itch import (
    AmbiguousRigError,
    ItchError,
    ProtocolMismatchError,
    Rig,
    RigInfo,
    RigNotFoundError,
    list_rigs,
)
from itch._cli import main
from itch._wire import SetLogLevel

HW_A = "60:55:F9:C0:27:18"


@pytest.fixture
def bench(monkeypatch: pytest.MonkeyPatch) -> FakeBench:
    return FakeBench(monkeypatch)


@pytest.mark.parametrize(
    ("platform", "lines"),
    [pytest.param("win32", False, id="windows"), pytest.param("linux", True, id="linux")],
)
def test_sets_dtr_and_rts_before_opening_and_never_after(
    bench: FakeBench, monkeypatch: pytest.MonkeyPatch, platform: str, lines: bool
) -> None:
    port = bench.rig("/dev/ttyACM0", HW_A)
    monkeypatch.setattr(sys, "platform", platform)
    with Rig.connect() as rig:
        assert rig.hardware_id == HW_A
    assert sorted(port.events[:2]) == [("dtr", lines), ("rts", lines)]
    assert port.events[2:] == [("open", True), ("close", None)]


HW_B = "60:55:F9:C0:27:19"
HW_C = "60:55:F9:C0:27:1A"


@pytest.mark.parametrize("name", ["/dev/ttyACM1", HW_B, HW_B.lower()])
def test_a_port_or_hardware_id_opens_only_that_rig(bench: FakeBench, name: str) -> None:
    others = [bench.rig("/dev/ttyACM0", HW_A, "bench3"), bench.rig("/dev/ttyACM2", HW_C)]
    bench.rig("/dev/ttyACM1", HW_B, "bench4")
    with Rig.connect(name) as rig:
        assert (rig.label, rig.hardware_id) == ("bench4", HW_B)
    assert not any(port.opened for port in others)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows ports have no stable links")
def test_a_stable_link_to_a_port_picks_that_rig(bench: FakeBench, tmp_path: Path) -> None:
    bench.rig("/dev/ttyACM0", HW_A)
    bench.rig("/dev/ttyACM1", HW_B)
    link = tmp_path / f"usb-Espressif_USB_JTAG_serial_debug_unit_{HW_B}-if00"
    link.symlink_to("/dev/ttyACM1")
    with Rig.connect(str(link)) as rig:
        assert rig.hardware_id == HW_B


def test_a_label_matches_ignoring_case_and_frees_the_others(bench: FakeBench) -> None:
    first = bench.rig("/dev/ttyACM0", HW_A, "bench3")
    bench.rig("/dev/ttyACM1", HW_B, "Bench4")
    with Rig.connect("BENCH4") as rig:
        assert (rig.label, rig.hardware_id) == ("Bench4", HW_B)
        assert first.events[-1] == ("close", None)


def test_a_label_lookup_sets_the_log_level_only_on_the_rig_it_picks(bench: FakeBench) -> None:
    other = bench.rig("/dev/ttyACM0", HW_A, "bench3")
    picked = bench.rig("/dev/ttyACM1", HW_B, "bench4")
    Rig.connect("bench4", log_level=logging.INFO).close()
    assert SetLogLevel(3) in [request.body for request in picked.requests]
    assert SetLogLevel(3) not in [request.body for request in other.requests]


def test_a_label_lookup_skips_rigs_in_use(bench: FakeBench) -> None:
    busy = bench.rig("/dev/ttyACM0", HW_A, "bench4", in_use=True)
    bench.rig("/dev/ttyACM1", HW_B, "bench4")
    with Rig.connect("bench4") as rig:
        assert rig.hardware_id == HW_B
    assert not busy.opened
    assert not busy.requests


def test_a_bare_connect_with_no_rig_says_none_is_plugged_in(bench: FakeBench) -> None:
    with pytest.raises(RigNotFoundError, match="No Rig is plugged in"):
        Rig.connect()


def test_a_bare_connect_with_several_rigs_lists_them_all(bench: FakeBench) -> None:
    bench.rig("/dev/ttyACM0", HW_A, "bench3")
    busy = bench.rig("/dev/ttyACM1", HW_B, "bench4", in_use=True)
    with pytest.raises(AmbiguousRigError) as raised:
        Rig.connect()
    assert str(raised.value).splitlines() == [
        "2 Rigs are plugged in; pass Rig.connect() the label, Hardware ID or port of one:",
        "  PORT          HARDWARE ID        LABEL   FIRMWARE",
        "  /dev/ttyACM0  60:55:F9:C0:27:18  bench3  1.0.0",
        "  /dev/ttyACM1  60:55:F9:C0:27:19  in use",
    ]
    assert not busy.requests


def test_an_ambiguous_label_lists_the_matches_and_frees_them(bench: FakeBench) -> None:
    ports = [
        bench.rig("/dev/ttyACM0", HW_A, "bench3"),
        bench.rig("/dev/ttyACM1", HW_B, "bench4"),
        bench.rig("/dev/ttyACM2", HW_C, "Bench3"),
    ]
    with pytest.raises(AmbiguousRigError) as raised:
        Rig.connect("bench3")
    assert str(raised.value).splitlines() == [
        "2 Rigs are labelled 'bench3'; pass Rig.connect() the Hardware ID or port of one:",
        "  PORT          HARDWARE ID        LABEL   FIRMWARE",
        "  /dev/ttyACM0  60:55:F9:C0:27:18  bench3  1.0.0",
        "  /dev/ttyACM2  60:55:F9:C0:27:1A  Bench3  1.0.0",
    ]
    assert all(port.events[-1] == ("close", None) for port in ports)


def test_a_label_not_found_reports_the_rigs_in_use(bench: FakeBench) -> None:
    bench.rig("/dev/ttyACM0", HW_A, "bench3")
    bench.rig("/dev/ttyACM1", HW_B, in_use=True)
    with pytest.raises(RigNotFoundError) as raised:
        Rig.connect("bench4")
    assert str(raised.value).splitlines()[0] == (
        "Rig 'bench4' not found; 1 Rig is in use by another program: /dev/ttyACM1. Rigs found:"
    )


def test_a_label_not_found_with_no_rig_says_none_is_plugged_in(bench: FakeBench) -> None:
    with pytest.raises(RigNotFoundError, match="'bench4' not found: no Rig is plugged in"):
        Rig.connect("bench4")


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("name", [None, "/dev/ttyACM0", HW_A])
def test_a_rig_in_use_by_name_says_so(
    bench: FakeBench, monkeypatch: pytest.MonkeyPatch, name: str | None, platform: str
) -> None:
    bench.rig("/dev/ttyACM0", HW_A, in_use=True)
    monkeypatch.setattr(sys, "platform", platform)
    with pytest.raises(
        RigNotFoundError, match=f"Rig {HW_A} on /dev/ttyACM0 is in use by another program"
    ):
        Rig.connect(name)


@pytest.mark.parametrize("name", ["/dev/ttyACM0", None, HW_B, "bench3"])
def test_a_hello_from_a_different_rig_than_the_port_lists_is_refused(
    bench: FakeBench, name: str | None
) -> None:
    port = bench.rig("/dev/ttyACM0", HW_A, "bench3")
    port.hardware_id = HW_B
    with pytest.raises(ItchError, match=f"says its Hardware ID is {HW_A}"):
        Rig.connect(name)
    assert port.events[-1] == ("close", None)


def test_list_rigs_shows_a_hello_from_a_different_rig_than_the_port_lists_as_an_error(
    bench: FakeBench,
) -> None:
    port = bench.rig("/dev/ttyACM0", HW_A, "bench3")
    port.hardware_id = HW_B
    (info,) = list_rigs()
    assert (info.port, info.hardware_id, info.label) == ("/dev/ttyACM0", HW_B, None)
    assert info.error is not None
    assert f"says its Hardware ID is {HW_A}" in info.error
    assert port.events[-1] == ("close", None)


@pytest.mark.parametrize("serial", ["60-55-F9-C0-27-18", "6055f9c02718"])
@pytest.mark.parametrize("name", ["/dev/ttyACM0", None, HW_A, "bench3"])
def test_a_serial_written_differently_still_matches_hello(
    bench: FakeBench, serial: str, name: str | None
) -> None:
    bench.rig("/dev/ttyACM0", HW_A, "bench3").hardware_id = serial
    with Rig.connect(name) as rig:
        assert rig.hardware_id == HW_A


@pytest.mark.skipif(sys.platform == "win32", reason="Linux and macOS report permissions by errno")
def test_a_port_the_user_may_not_open_says_why(bench: FakeBench) -> None:
    bench.rig("/dev/ttyACM0", HW_A).open_errno = errno.EACCES
    with pytest.raises(ItchError, match=r"Permission denied.*dialout"):
        Rig.connect()


def test_list_rigs_shows_free_rigs_and_rigs_in_use(bench: FakeBench) -> None:
    bench.rig("/dev/ttyACM0", HW_A, "bench3")
    busy = bench.rig("/dev/ttyACM1", HW_B, "bench4", in_use=True)
    other = ListPortInfo("/dev/ttyUSB0", skip_link_detection=True)
    other.vid, other.pid, other.serial_number = 0x0403, 0x6001, "A10K1234"
    bench.other_devices.append(other)
    assert list_rigs() == [
        RigInfo("/dev/ttyACM0", HW_A, "bench3", "1.0.0"),
        RigInfo("/dev/ttyACM1", HW_B, None, None),
    ]
    assert not busy.requests


def test_itch_list_prints_the_bench(bench: FakeBench, capsys: pytest.CaptureFixture[str]) -> None:
    bench.rig("/dev/ttyACM0", HW_A, "bench3")
    bench.rig("/dev/ttyACM1", HW_B, in_use=True)
    assert main(["list"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "PORT          HARDWARE ID        LABEL   FIRMWARE",
        "/dev/ttyACM0  60:55:F9:C0:27:18  bench3  1.0.0",
        "/dev/ttyACM1  60:55:F9:C0:27:19  in use",
    ]


def test_itch_list_says_when_no_rig_is_plugged_in(
    bench: FakeBench, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list"]) == 0
    assert capsys.readouterr().out == "No Rig is plugged in.\n"


def _broken(bench: FakeBench, device: str, hardware_id: str) -> None:
    """Plugs in a free Rig that speaks another protocol."""
    port = bench.rig(device, hardware_id, "bench4")
    assert port.hello is not None
    port.hello = dataclasses.replace(port.hello, protocol=2)


def test_list_rigs_records_a_rig_that_fails_and_lists_the_rest(bench: FakeBench) -> None:
    _broken(bench, "/dev/ttyACM0", HW_A)
    bench.rig("/dev/ttyACM1", HW_B, "bench3")
    broken, ok = list_rigs()
    assert ok == RigInfo("/dev/ttyACM1", HW_B, "bench3", "1.0.0")
    assert (broken.port, broken.label, broken.in_use) == ("/dev/ttyACM0", None, False)
    assert broken.error is not None
    assert "speaks protocol 2" in broken.error


def test_itch_list_shows_a_rig_that_fails(
    bench: FakeBench, capsys: pytest.CaptureFixture[str]
) -> None:
    _broken(bench, "/dev/ttyACM0", HW_A)
    bench.rig("/dev/ttyACM1", HW_B, "bench3")
    assert main(["list"]) == 0
    header, broken, ok = capsys.readouterr().out.splitlines()
    assert header == "PORT          HARDWARE ID        LABEL   FIRMWARE"
    assert broken.startswith("/dev/ttyACM0  60:55:F9:C0:27:18  error   Rig ")
    assert "speaks protocol 2" in broken
    assert ok == "/dev/ttyACM1  60:55:F9:C0:27:19  bench3  1.0.0"


def test_a_label_lookup_skips_rigs_that_fail(bench: FakeBench) -> None:
    _broken(bench, "/dev/ttyACM0", HW_A)
    bench.rig("/dev/ttyACM1", HW_B, "bench4")
    with Rig.connect("bench4") as rig:
        assert rig.hardware_id == HW_B


def test_a_label_not_found_lists_the_rigs_that_fail(bench: FakeBench) -> None:
    _broken(bench, "/dev/ttyACM0", HW_A)
    with pytest.raises(RigNotFoundError) as raised:
        Rig.connect("bench4")
    lines = str(raised.value).splitlines()
    assert lines[0] == "Rig 'bench4' not found. Rigs found:"
    assert lines[2].startswith("  /dev/ttyACM0  60:55:F9:C0:27:18  error  Rig ")


@pytest.mark.parametrize("name", [None, "/dev/ttyACM0", HW_A])
def test_naming_a_rig_that_fails_raises_its_error(bench: FakeBench, name: str | None) -> None:
    _broken(bench, "/dev/ttyACM0", HW_A)
    with pytest.raises(ProtocolMismatchError, match="speaks protocol 2"):
        Rig.connect(name)
