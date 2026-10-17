"""Rig error codes and the exception hierarchy."""

import pytest
from conftest import RunningSim
from scripted_rig import ScriptedRig, after_connecting

import itch
from itch import HardwareFaultError, ItchError, LeaseError, LeaseRequiredError, Rig
from itch._wire import ErrorCode, ErrorResponse

HOLDER = "qa@bench-pc acme_test.py"

# What each code raises, and a phrase its message must hold.
RAISES: dict[ErrorCode, tuple[type[ItchError], str]] = {
    ErrorCode.UnknownRequest: (ItchError, "doesn't know GetChannels"),
    ErrorCode.UnsupportedVersion: (ItchError, "update the Rig or itch-py"),
    ErrorCode.Malformed: (ItchError, "itch-py bug"),
    ErrorCode.LeaseRequired: (LeaseRequiredError, "needs a session"),
    ErrorCode.LeaseHeld: (LeaseError, f"in use by {HOLDER}"),
    ErrorCode.LeaseLost: (LeaseError, f"taken over by {HOLDER}"),
    ErrorCode.Busy: (ItchError, "busy"),
    ErrorCode.HardwareFault: (HardwareFaultError, "not the DUT"),
    ErrorCode.StorageFault: (ItchError, "couldn't save"),
    ErrorCode.Internal: (ItchError, "internal error"),
}


def refusing(code: int, detail: str = "") -> ScriptedRig:
    """A peer that refuses everything after connecting with `code`."""
    return after_connecting(
        lambda request: [ErrorResponse(request.body.TYPE, request.request_id, code, detail)]
    )


def test_every_error_code_has_an_exception() -> None:
    assert set(RAISES) == set(ErrorCode)


@pytest.mark.parametrize("code", list(ErrorCode), ids=lambda code: code.name)
def test_an_error_reply_raises_its_exception(code: ErrorCode) -> None:
    error, phrase = RAISES[code]
    detail = HOLDER if code in (ErrorCode.LeaseHeld, ErrorCode.LeaseLost) else ""
    with (
        refusing(code, detail) as peer,
        Rig.connect(peer.url) as rig,
        pytest.raises(error) as raised,
    ):
        rig.get_channels()
    message = str(raised.value)
    assert phrase in message, message
    assert "error code" not in message, message


def test_an_unknown_error_code_raises_a_generic_itch_error() -> None:
    with (
        refusing(99, "new trouble") as peer,
        Rig.connect(peer.url) as rig,
        pytest.raises(ItchError) as raised,
    ):
        rig.get_channels()
    assert type(raised.value) is ItchError
    assert str(raised.value) == "Rig bench3 refused GetChannels with error code 99: new trouble"


def test_every_exported_error_is_an_itch_error() -> None:
    errors = [
        obj
        for name in itch.__all__
        if isinstance(obj := getattr(itch, name), type) and name.endswith("Error")
    ]
    assert len(errors) >= 10
    assert all(issubclass(error, ItchError) for error in errors)


def test_a_rig_whose_expander_is_dead_raises_hardware_fault_error() -> None:
    with RunningSim("--hardware-fault") as sim, Rig.connect(sim.url) as rig, rig.session():
        with pytest.raises(HardwareFaultError, match="not the DUT"):
            rig.set_channel(1, "on")
        with pytest.raises(HardwareFaultError):
            rig.clear()
        assert set(rig.get_channels().values()) == {"off"}
        assert rig.status().expander_faults == 1
