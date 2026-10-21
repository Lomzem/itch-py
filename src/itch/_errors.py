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
    """The Rig runs a development build, built from uncommitted code."""


class LockedError(ItchError):
    """Someone else holds the Rig's Lock, so it refused a change or a Lock.

    The message names the Holder for people to read. Read `rig.status().holder` to get it as data.
    """

    def __init__(self, rig: str, detail: str) -> None:
        super().__init__(
            f"Rig {rig} is Locked by {detail or 'another Holder'}; pass take_over=True to take "
            "it over."
        )


class NotRespondingError(ItchError):
    """A request went unanswered, even after a retry."""

    def __init__(self, rig: str) -> None:
        super().__init__(f"Rig {rig} isn't responding.")


class DisconnectedError(ItchError):
    """The connection to the Rig closed, as after an unplug, a reboot or a Wi-Fi drop.

    itch-py doesn't reconnect. Connecting again under the same Holder picks the Lock back up. A
    reboot turns every Channel off, so check them, or run the script again.

    After the Rig accepts new Wi-Fi or address settings over the network, the connection is
    expected to end, and the message says to reconnect after the network change. After
    `disconnect()`, the message says this script disconnected.
    """

    def __init__(self, rig: str, *, network_changed: bool = False, closed: bool = False) -> None:
        if closed:
            message = (
                f"Rig {rig} was disconnected by this script; connect again with Rig.connect() "
                "to use it."
            )
        elif network_changed:
            message = (
                f"Rig {rig} disconnected after its network settings changed, as expected; "
                "reconnect after the network change."
            )
        else:
            message = (
                f"Rig {rig} disconnected; reconnect, or run the script again. The same Holder "
                "picks its Lock back up."
            )
        super().__init__(message)


class HardwareFaultError(ItchError):
    """The Rig's Channel expander is unreachable, so the Rig holds every Channel off.

    The Rig, not the DUT, is at fault. It keeps retrying, and restores the Channels once
    the expander is back.
    """


class StorageFaultError(ItchError):
    """The Rig couldn't save a setting, such as its label, to its flash, so it kept the old one."""


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
    error = ItchError
    match code:
        case ErrorCode.Locked:
            return LockedError(rig, detail)
        case ErrorCode.UnknownRequest:
            message = f"Rig {rig} doesn't know {request}. Have the dev update the Rig or itch-py."
        case ErrorCode.Malformed:
            message = f"Rig {rig} couldn't decode {request}. This is an itch-py bug; tell the dev."
        case ErrorCode.Busy:
            message = f"Rig {rig} is busy: its request queue is full."
        case ErrorCode.HardwareFault:
            message = (
                f"Rig {rig} has a hardware fault: its Channel expander isn't responding, "
                "so every Channel is off. The Rig, not the DUT, is broken; tell the dev."
            )
            error = HardwareFaultError
        case ErrorCode.StorageFault:
            message = f"Rig {rig} couldn't save the setting to its flash; tell the dev."
            error = StorageFaultError
        case ErrorCode.Internal:
            message = f"Rig {rig} hit an internal error answering {request}; tell the dev."
        case _:
            message = f"Rig {rig} refused {request} with error code {code}"
            return ItchError(f"{message}: {detail}" if detail else f"{message}.")
    return error(f"{message} ({detail})" if detail else message)
