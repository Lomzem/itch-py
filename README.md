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

## Set and read Channels

Channels are numbered 1 to 16, as on the board. `"on"` means the contact is closed, like a DIP switch's ON position. Changing Channels needs a session; reading them doesn't.

```python
with rig.session():
    rig.set_channel(3, "on")
    rig.set_channels({1: "on", 5: "off"})  # one write; other Channels stay as they are
    rig.clear()  # every Channel off

print(rig.get_channel(3))  # "off"
print(rig.get_channels())  # {1: "off", 2: "off", ..., 16: "off"}
```

The session keeps itself alive while the script sleeps or blocks. In Jupyter or a REPL, keep it across cells with `s = rig.session()` and later `s.release()`. Leaving the session leaves the Channels as they are.

## Development

Uses [uv](https://docs.astral.sh/uv/):

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

The tests run against a real `itch-sim` and the protocol's conformance vectors. They find them through `ITCH_SIM` (an `itch-sim` binary) and `ITCH_VECTORS` (`vectors-v1.json`). Otherwise they use an `itch` checkout, given by `ITCH_REPO` or found next to this one, building the sim there with `cargo build -p itch-sim`.
