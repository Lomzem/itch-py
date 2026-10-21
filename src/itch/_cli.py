"""The `itch` command line."""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence
from ipaddress import IPv4Address, IPv4Interface

from itch._discovery import rig_table
from itch._errors import ItchError
from itch._mdns import BROWSE_TIMEOUT
from itch._rig import Rig, list_rigs


def main(argv: Sequence[str] | None = None) -> int:
    """Runs `itch` with `argv`, by default the process arguments, and returns its exit status."""
    parser = argparse.ArgumentParser(prog="itch", description="Manage itch Rigs.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "list",
        help="show the Rigs plugged in over USB or on the network",
        description=(
            "Show the Rigs plugged in over USB, without disturbing those in use, then those "
            f"advertised on the network within {BROWSE_TIMEOUT:g} seconds."
        ),
    )
    label = commands.add_parser(
        "label",
        help="rename a Rig",
        description="Rename a Rig. An empty label restores the default.",
    )
    label.add_argument("rig", help=_RIG_HELP)
    label.add_argument("label", help='the new label, at most 64 bytes; "" restores the default')
    _add_wifi(commands.add_parser)
    _add_address(commands.add_parser)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            rigs = list_rigs()
            print("\n".join(rig_table(rigs)) if rigs else "No Rig is plugged in or on the network.")
            return 0
        if args.command == "wifi" and args.action == "set":
            args.passphrase = _passphrase(args.ssid, args.passphrase_stdin)
        with Rig.connect(args.rig) as rig:  # Locks the Rig until the command ends.
            print(_change(rig, args))
    except (ItchError, ValueError) as err:
        print(f"itch: {err}", file=sys.stderr)
        return 1
    return 0


_RIG_HELP = "the Rig's label, Hardware ID, port or tcp://host:port"

_RECONNECT = (
    "Over the network, the Rig may drop the connection as it changes; reconnect after the change."
)


def _add_wifi(add_parser: Callable[..., argparse.ArgumentParser]) -> None:
    wifi = add_parser(
        "wifi",
        help="set or clear a Rig's Wi-Fi credentials",
        description="Set or clear the Wi-Fi network a Rig joins. Each command Locks the Rig.",
    )
    actions = wifi.add_subparsers(dest="action", required=True)
    wifi_set = actions.add_parser(
        "set",
        help="give a Rig credentials for a Wi-Fi network",
        description=(
            "Give a Rig credentials for a Wi-Fi network, replacing any it had. The passphrase is "
            "asked for without echoing it, or read from the first line of standard input with "
            f"--passphrase-stdin. {_RECONNECT}"
        ),
    )
    wifi_set.add_argument("rig", help=_RIG_HELP)
    wifi_set.add_argument("ssid", help="the network's name, 1 to 32 bytes")
    wifi_set.add_argument(
        "--passphrase-stdin",
        action="store_true",
        help="read the passphrase, 8 to 63 bytes, from standard input instead of asking",
    )
    wifi_clear = actions.add_parser(
        "clear",
        help="forget a Rig's Wi-Fi credentials",
        description=f"Forget a Rig's Wi-Fi credentials, so it works over USB alone. {_RECONNECT}",
    )
    wifi_clear.add_argument("rig", help=_RIG_HELP)


def _add_address(add_parser: Callable[..., argparse.ArgumentParser]) -> None:
    address = add_parser(
        "address",
        help="set how a Rig takes its address on Wi-Fi",
        description=(
            "Set how a Rig takes its IPv4 address on Wi-Fi: static or from DHCP. Each command "
            "Locks the Rig."
        ),
    )
    actions = address.add_subparsers(dest="action", required=True)
    static = actions.add_parser(
        "static",
        help="give a Rig a static address",
        description=(
            "Give a Rig a static IPv4 address on Wi-Fi. The Rig applies it as given, with no "
            "conflict check and no fallback to DHCP: a wrong address strands its Wi-Fi until "
            f"you fix it over USB. {_RECONNECT}"
        ),
    )
    static.add_argument("rig", help=_RIG_HELP)
    static.add_argument(
        "address", type=IPv4Interface, help="the address with its prefix, such as 192.0.2.10/24"
    )
    static.add_argument("--gateway", type=IPv4Address, help="the gateway, such as 192.0.2.1")
    dhcp = actions.add_parser(
        "dhcp",
        help="have a Rig take its address from DHCP",
        description=f"Have a Rig take its IPv4 address on Wi-Fi from DHCP. {_RECONNECT}",
    )
    dhcp.add_argument("rig", help=_RIG_HELP)


def _passphrase(ssid: str, from_stdin: bool) -> str:
    """Reads the passphrase for `ssid` without echoing it, or from standard input's first line."""
    if from_stdin:
        return sys.stdin.readline().removesuffix("\n").removesuffix("\r")
    return getpass.getpass(f"Passphrase for {ssid}: ")


def _change(rig: Rig, args: argparse.Namespace) -> str:
    """Makes the change the command asks of `rig`, and says what it did."""
    name = rig.label
    match args.command, getattr(args, "action", None):
        case "wifi", "set":
            rig.set_wifi(args.ssid, args.passphrase)
            return f"Rig {name} joins {args.ssid}."
        case "wifi", "clear":
            rig.clear_wifi()
            return f"Rig {name} has no Wi-Fi credentials now; reach it over USB."
        case "address", "static":
            rig.set_address(args.address, args.gateway)
            gateway = f" with gateway {args.gateway}" if args.gateway else ""
            return f"Rig {name} uses {args.address}{gateway}."
        case "address", "dhcp":
            rig.use_dhcp()
            return f"Rig {name} takes its address from DHCP."
        case _:
            rig.set_label(args.label)
            return f"Rig {name} is now {rig.label}."
