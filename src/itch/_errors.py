from itch._wire import ErrorCode


class ItchError(Exception):
    """Base class of every error itch-py raises. Bad arguments raise `ValueError` instead."""


class ProtocolMismatchError(ItchError):
    """The Rig speaks a different protocol version from this itch-py."""

    def __init__(self, rig: str, rig_protocol: int, client_protocol: int) -> None:
        super().__init__(
            f"Rig {rig} speaks protocol {rig_protocol}, but this itch-py speaks protocol "
            f"{client_protocol}. Have the dev update the Rig or itch-py."
        )
        self.rig_protocol = rig_protocol
        self.client_protocol = client_protocol


class DevelopmentBuildWarning(UserWarning):
    """The Rig runs a development build: WiFi enabled, or built from uncommitted code."""


class LeaseError(ItchError):
    """A problem with the Lease that lets a script change a Rig's Channels."""


class LeaseHeldError(LeaseError):
    """Someone else holds the Rig. `.holder` says who."""

    def __init__(self, rig: str, holder: str) -> None:
        super().__init__(
            f"Rig {rig} is in use by {holder}. If that script is dead, take the Rig over "
            "with `rig.session(takeover=True)`."
        )
        self.holder = holder


class LeaseLostError(LeaseError):
    """Someone else took the Rig from this session. `.reason` names the new Holder.

    The session no longer controls the Rig, so its changes fail until it is released.
    """

    def __init__(self, rig: str, reason: str) -> None:
        super().__init__(
            f"Rig {rig} was taken over by {reason}; this script no longer controls it."
        )
        self.reason = reason


class LeaseRequiredError(LeaseError):
    """A write outside a Session."""

    def __init__(self) -> None:
        super().__init__(
            "Changing Channels needs a session: wrap the writes in `with rig.session():`."
        )


class NotRespondingError(ItchError):
    """A request went unanswered, even after a retry."""

    def __init__(self, rig: str) -> None:
        super().__init__(f"Rig {rig} isn't responding.")


class DisconnectedError(ItchError):
    """The connection to the Rig closed, as after an unplug or a reboot. itch-py doesn't reconnect.

    A reboot turns every Channel off, so the script must start again.
    """

    def __init__(self) -> None:
        super().__init__("Rig disconnected; run the script again.")


class StorageFaultError(ItchError):
    """The Rig couldn't save a setting, such as its label, to its flash."""

    def __init__(self, rig: str, detail: str = "") -> None:
        message = f"Rig {rig} couldn't save the setting to its flash; tell the dev."
        super().__init__(f"{message} ({detail})" if detail else message)


class RigNotFoundError(ItchError):
    """No Rig matches the name given to `Rig.connect()`."""


class AmbiguousRigError(ItchError):
    """More than one Rig matches the name given to `Rig.connect()`."""


class ProfileError(ItchError):
    """A Profile is defined wrongly."""


class BatchConflictError(ItchError):
    """Fields in one batch disagree on a shared Channel."""


def rig_error(rig: str, request: str, code: int, detail: str) -> ItchError:
    """The exception for a Rig refusing `request` with error `code`."""
    match code:
        case ErrorCode.LeaseRequired:
            return LeaseRequiredError()
        case ErrorCode.LeaseHeld:
            return LeaseHeldError(rig, detail)
        case ErrorCode.LeaseLost:
            return LeaseLostError(rig, detail)
        case ErrorCode.UnknownRequest:
            message = f"Rig {rig} doesn't know {request}. Have the dev update the Rig or itch-py."
        case ErrorCode.UnsupportedVersion:
            message = (
                f"Rig {rig} can't answer {request} in this protocol version. "
                "Have the dev update the Rig or itch-py."
            )
        case ErrorCode.Malformed:
            message = f"Rig {rig} couldn't decode {request}. This is an itch-py bug; tell the dev."
        case ErrorCode.Busy:
            message = f"Rig {rig} is busy: its request queue is full."
        case ErrorCode.HardwareFault:
            message = (
                f"Rig {rig} has a hardware fault: its Channel expander isn't responding. "
                "The Rig, not the DUT, is broken; tell the dev."
            )
        case ErrorCode.StorageFault:
            return StorageFaultError(rig, detail)
        case ErrorCode.Internal:
            message = f"Rig {rig} hit an internal error answering {request}; tell the dev."
        case _:
            message = f"Rig {rig} refused {request} with error code {code}"
            return ItchError(f"{message}: {detail}" if detail else f"{message}.")
    return ItchError(f"{message} ({detail})" if detail else message)
