"""The `itch` command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from itch._discovery import rig_table
from itch._errors import ItchError
from itch._rig import Rig, list_rigs


def main(argv: Sequence[str] | None = None) -> int:
    """Runs `itch` with `argv`, by default the process arguments, and returns its exit status."""
    parser = argparse.ArgumentParser(prog="itch", description="Manage itch Rigs.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "list",
        help="show the Rigs plugged in over USB",
        description="Show the Rigs plugged in over USB, without disturbing those in use.",
    )
    label = commands.add_parser(
        "label",
        help="rename a Rig",
        description="Rename a Rig. An empty label restores the default.",
    )
    label.add_argument("rig", help="the Rig's label, Hardware ID, port or tcp://host:port")
    label.add_argument("label", help='the new label, at most 64 bytes; "" restores the default')
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            rigs = list_rigs()
            print("\n".join(rig_table(rigs)) if rigs else "No Rig is plugged in.")
            return 0
        with Rig.connect(args.rig) as rig:
            old = rig.label
            with rig.session():
                rig.set_label(args.label)
            print(f"Rig {old} is now {rig.label}.")
    except (ItchError, ValueError) as err:
        print(f"itch: {err}", file=sys.stderr)
        return 1
    return 0
