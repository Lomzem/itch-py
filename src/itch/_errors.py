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


class LeaseRequiredError(LeaseError):
    """A write outside a Session."""

    def __init__(self) -> None:
        super().__init__(
            "Changing Channels needs a session: wrap the writes in `with rig.session():`."
        )


class ProfileError(ItchError):
    """A Profile is written wrongly. Raised when the Profile is defined, naming the mistake."""
