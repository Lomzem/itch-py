"""A TCP client outside Rig's in-process reconnect lifecycle."""

from urllib.parse import urlsplit

from itch._connection import Connection
from itch._transport import TcpTransport


def other_client(url: str) -> Connection:
    """Opens the lower protocol seam to stand in for a client in another process."""
    address = urlsplit(url)
    assert address.hostname is not None
    assert address.port is not None
    return Connection.open(TcpTransport(address.hostname, address.port))
