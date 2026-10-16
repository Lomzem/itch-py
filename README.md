# itch-py

Python client for [itch](https://github.com/Lomzem/itch) Rigs: drive a DUT's DIP switches from a script.

## Install

Needs Python 3.11 or later.

```sh
pip install "itch @ git+https://github.com/Lomzem/itch-py.git"
```

## Connect to a Rig

Start `itch-sim`, which prints the address it listens on, then:

```python
from itch import Rig

with Rig.connect("tcp://127.0.0.1:<port>") as rig:
    print(rig.label, rig.hardware_id, rig.firmware_version)
```

## Development

Uses [uv](https://docs.astral.sh/uv/):

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

The tests run against a real `itch-sim` and the protocol's conformance vectors. They find them through `ITCH_SIM` (an `itch-sim` binary) and `ITCH_VECTORS` (`vectors-v1.json`). Otherwise they use an `itch` checkout, given by `ITCH_REPO` or found next to this one, building the sim there with `cargo build -p itch-sim`.
