"""The `itch` command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from itch._errors import ItchError
from itch._rig import Rig


def main(argv: Sequence[str] | None = None) -> int:
    """Runs `itch` with `argv`, by default the process arguments, and returns its exit status."""
    parser = argparse.ArgumentParser(prog="itch", description="Manage itch Rigs.")
    commands = parser.add_subparsers(dest="command", required=True)
    label = commands.add_parser(
        "label",
        help="rename a Rig",
        description="Rename a Rig. An empty label restores the default.",
    )
    label.add_argument("rig", help="the Rig, such as tcp://127.0.0.1:4000")
    label.add_argument("label", help='the new label, at most 64 bytes; "" restores the default')
    args = parser.parse_args(argv)
    try:
        with Rig.connect(args.rig) as rig:
            old = rig.label
            with rig.session():
                rig.set_label(args.label)
            print(f"Rig {old} is now {rig.label}.")
    except (ItchError, ValueError) as err:
        print(f"itch: {err}", file=sys.stderr)
        return 1
    return 0
