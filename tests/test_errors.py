"""Rig error codes and the exception hierarchy."""

import pytest
from scripted_rig import ACME_HELLO, ScriptedRig

import itch
from itch import ItchError, LeaseError, LeaseRequiredError, Rig
from itch._wire import ErrorCode, ErrorResponse, Hello, Message, OkResponse, Request

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
    ErrorCode.HardwareFault: (ItchError, "not the DUT"),
    ErrorCode.StorageFault: (ItchError, "couldn't save"),
    ErrorCode.Internal: (ItchError, "internal error"),
}


def refusing(code: int, detail: str = "") -> ScriptedRig:
    """A peer that answers `Hello` and refuses everything else with `code`."""

    def answer(request: Request) -> list[Message]:
        if isinstance(request.body, Hello):
            return [OkResponse(request.request_id, ACME_HELLO)]
        return [ErrorResponse(request.body.TYPE, request.request_id, code, detail)]

    return ScriptedRig(answer)


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
