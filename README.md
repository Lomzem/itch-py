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

Plug the Rig into the PC over USB. With one Rig plugged in, connect without naming it:

```python
from itch import Rig

with Rig.connect() as rig:
    print(rig.label, rig.hardware_id, rig.firmware_version)
```

With several, name the one you want by its label, Hardware ID or port, ignoring case:

```python
Rig.connect("bench3")
Rig.connect("60:55:F9:C0:27:18")
Rig.connect("COM4")  # or "/dev/ttyACM0", or a stable /dev/serial/by-id/... link
```

`itch list` shows what is plugged in. Rigs another script has open show as in use, and itch-py sends them nothing, so listing or connecting doesn't disturb a running test:

```sh
$ itch list
PORT          HARDWARE ID        LABEL   FIRMWARE
/dev/ttyACM0  60:55:F9:C0:27:18  bench3  1.0.0
/dev/ttyACM1  60:55:F9:C0:27:19  in use
```

From Python, `itch.list_rigs()` returns the same list. On Linux, "in use" means another itch-py script, or any program that locks the port as itch-py does; a serial monitor such as `screen` doesn't lock it.

On Linux, your user needs access to the port: add yourself to the group that owns `/dev/ttyACM*` (`dialout` on Debian and Ubuntu, `uucp` on Arch), then log in again.

### The simulator

Without a Rig, use the simulator. Download `itch-sim-windows-x86_64.exe` or `itch-sim-linux-x86_64` from the [`itch` release](https://github.com/Lomzem/itch/releases) listed for your itch-py release under [Releases](#releases). Run it and it prints the address it listens on:

```sh
$ chmod +x itch-sim-linux-x86_64
$ ./itch-sim-linux-x86_64
itch-sim listening on tcp://127.0.0.1:49152
```

Then connect to that address:

```python
with Rig.connect("tcp://127.0.0.1:<port>") as rig:
    ...
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

## Sharing a Rig

One script at a time holds a Rig. If someone else holds it, `rig.session()` raises `LeaseHeldError` at once, naming them (`user@host script.py` by default; pass `holder="..."` to say more, up to 64 bytes). If their script is dead, take the Rig over:

```python
with rig.session(takeover=True):
    ...
```

The script you took it from gets `LeaseLostError` on its next change. A session left idle too long (a paused debugger, say) carries on as before if nobody else took the Rig.

## Rename a Rig

A new Rig is labelled `itch-` plus the end of its Hardware ID, such as `itch-C02718`. Give it a bench name, up to 64 bytes, inside a session; the Rig keeps it across reboots, and an empty label restores the default:

```python
with rig.session():
    rig.set_label("bench3")
```

Or from the command line:

```sh
itch label itch-C02718 bench3
```

`itch label` takes the same names as `Rig.connect()`, including a port or `tcp://host:port`.

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
