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

## Drive a DUT with a Profile

A Profile names a DUT model's settings, so a script says `"1080p"` instead of which Channels to turn on. Write one as a short class. Each Field lists the Channels it uses, and each Value lists one `"on"`/`"off"` per Channel, in the same order:

```python
from itch import Profile, alias, field


class AcmeWidget(Profile):
    resolution = field(
        channels=[1, 2],
        values={
            "720p": ["on", "off"],
            "1080p": ["off", "on"],
        },
    )
    mode = field(
        channels=[4, 5, 6],
        values={
            "cinema": ["off", "off", "off"],
            "night": [
                ["on", "off", "off"],
                ["on", "off", "on"],
            ],  # two Encodings; the first is the default
            "movie": alias("cinema"),  # another name for "cinema"
        },
    )
```

Then drive the DUT through it. In VS Code, the Values autocomplete inside `set("…")`, and a misspelt one is underlined once type checking is on (`"python.analysis.typeCheckingMode": "basic"`):

```python
dut = AcmeWidget(rig)
with rig.session():
    dut.resolution.set("1080p")
    dut.mode.set("night", encoding=2)
    for encoding in dut.mode.all_encodings():  # every Encoding of every Value
        encoding.set()
        ...  # check the DUT

print(dut.mode.get())  # "night"; an alias reads back as the Value it names
print(dut.mode.get_encoding())  # mode="night" Encoding 2 of 2 ["on", "off", "on"]
```

A mistake in a Profile, such as a wrong number of positions, raises a `ProfileError` saying what to fix as soon as the Profile is loaded.

## Rig logs

The Rig's own log messages are off by default. To see them in your test log, pass a Python logging level. Messages at that level and above go to the `itch.rig` logger:

```python
import logging

logging.basicConfig(level=logging.INFO)
with Rig.connect("tcp://127.0.0.1:<port>", log_level=logging.INFO) as rig:
    ...
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
