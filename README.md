# itch-py

Python client for [itch](https://github.com/Lomzem/itch) Rigs: drive a DUT's DIP switches from a script.

## Install

Needs Python 3.11 or later. Install a tagged release, replacing `vX.Y.Z` with one from the table under [Releases](#releases):

```sh
pip install "itch @ git+https://github.com/Lomzem/itch-py.git@vX.Y.Z"
```

or, in a `requirements.txt` or `pyproject.toml` dependency list:

```
itch @ git+https://github.com/Lomzem/itch-py.git@vX.Y.Z
```

## Connect to a Rig

Without a Rig, use the simulator. Download `itch-sim-windows-x86_64.exe` or `itch-sim-linux-x86_64` from the [`itch` release](https://github.com/Lomzem/itch/releases) listed for your itch-py release under [Releases](#releases). Run it and it prints the address it listens on:

```sh
$ chmod +x itch-sim-linux-x86_64
$ ./itch-sim-linux-x86_64
itch-sim listening on tcp://127.0.0.1:49152
```

Then connect to that address:

```python
from itch import Rig

with Rig.connect("tcp://127.0.0.1:<port>") as rig:
    print(rig.label, rig.hardware_id, rig.firmware_version)
```

## Releases

Each itch-py release is tested against one `itch` release: its `itch-sim` and its firmware.

| itch-py | Tested with `itch` (sim and firmware) |
| ------- | ------------------------------------- |
| unreleased | v0.1.0 |

## Development

Uses [uv](https://docs.astral.sh/uv/):

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

The tests run against a real `itch-sim` and the protocol's conformance vectors. They take them from the first of:

1. `ITCH_SIM` (an `itch-sim` binary) and `ITCH_VECTORS` (`vectors-v1.json`).
2. An `itch` checkout, given by `ITCH_REPO` or found next to this one. The sim is built there with `cargo build -p itch-sim`.
3. The `itch` release pinned by `TAG` in `tests/itch_release.py`. The first run downloads its sim and vectors into a local cache and checks them against the release manifest; later runs work offline. CI uses this.

To move to a new `itch` release, bump `TAG` and add a row to the table under [Releases](#releases).
