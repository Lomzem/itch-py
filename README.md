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

However you name it, itch-py checks that the Rig that answers has the Hardware ID its USB port lists, so a port reshuffle can't send your script to another DUT.

`itch list` shows what is plugged in, then the Rigs on the network (see [Rigs on Wi-Fi](#rigs-on-wi-fi)). Rigs another script has open show as in use, and itch-py sends them nothing, so listing or connecting doesn't disturb a running test:

```sh
$ itch list
PORT                   HARDWARE ID        LABEL   FIRMWARE
/dev/ttyACM0           60:55:F9:C0:27:18  bench3  1.0.0
/dev/ttyACM1           60:55:F9:C0:27:19  in use
/dev/ttyACM2           60:55:F9:C0:27:1A  error   Rig /dev/ttyACM2 speaks protocol 1, but this itch-py speaks protocol 3. Have the dev update the Rig or itch-py.
tcp://192.0.2.11:7878  60:55:F9:C0:27:1B  bench5
```

A free Rig that itch-py can't open or talk to shows its error in the list, and connecting by label skips it. Connecting to it by port or Hardware ID raises that error.

From Python, `itch.list_rigs()` returns the same list. On Linux, "in use" means another itch-py script, or any program that locks the port as itch-py does; a serial monitor such as `screen` doesn't lock it.

### Rigs on Wi-Fi

A Rig that has joined Wi-Fi advertises itself on the network over mDNS (`_itch._tcp`), by its label and Hardware ID. When no Rig plugged in over USB has the label or Hardware ID you name, `Rig.connect()` browses the network for one, for 3 seconds by default:

```python
Rig.connect("bench5")  # USB first, then the network
Rig.connect("bench5", browse_timeout=5)  # browse longer on a slow network
```

USB always wins: a Rig plugged in is used over USB even if it is also on the network, and `itch list` shows it once, as plugged in. `Rig.connect()` with no name never picks a Rig on the network. `itch list` and `list_rigs()` browse for the same 3 seconds (`list_rigs(browse_timeout=...)` changes it), and list Rigs on the network as they advertise themselves, without connecting to them, so their firmware is blank.

After connecting, itch-py checks that the Rig's own `Hello` gives the label you asked for and the Hardware ID it advertised. That matters because mDNS can mislead: a label over 63 bytes is advertised cut to its first 63, and two Rigs can advertise the same label. If two Rigs on the network answer to one label, `Rig.connect()` raises `AmbiguousRigError` and lists both. itch-py collects every answer heard during the whole browse, but it can only report Rigs whose answers reach it in time, so it can't promise to notice a duplicate; the `Hello` check is the backstop. Give each Rig its own label.

If mDNS is blocked or slow on your network, connect by address instead. This skips discovery entirely:

```python
Rig.connect("tcp://192.0.2.10:7878")
```

A Rig serves at most 4 network connections besides USB, and closes a fifth before answering. itch-py reports that straight away as "Rig at tcp://… closed the connection before replying to Hello; it may already have 4 network connections." Close a script you no longer need, or use USB.

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

Channels are numbered 1 to 16, as on the board. `"on"` means the contact is closed, like a DIP switch's ON position.

```python
rig.set_channel(3, "on")
rig.set_channels({1: "on", 5: "off"})  # one write; other Channels stay as they are
rig.clear()  # every Channel off

print(rig.get_channel(3))  # "off"
print(rig.get_channels())  # {1: "off", 2: "off", ..., 16: "off"}
print(rig.get_channels([1, 5]))  # {1: "off", 5: "off"}
```

The Rig keeps its Channels when the script ends or disconnects: closing never turns them off. The next script, or a reconnect, finds them as they were left.

## Sharing a Rig

Connecting Locks the Rig, so nobody else's script can change it until yours closes. Anyone may still read it. The Lock is held under your script's Holder: `user@host` by default, such as `qa@bench-pc`. Pass `holder="..."` to name it yourself, up to 64 bytes:

```python
Rig.connect("bench3", holder="qa@bench-pc")
```

`rig.holder` is the Holder your script uses, and `rig.status().holder` says who holds the Lock, or `None`.

If someone else holds the Lock, connecting raises `LockedError` naming them:

```
itch.LockedError: Rig bench3 is Locked by alice@ws3; pass take_over=True to take it over.
```

To look without Locking, pass `lock=False`. Reads work; changes raise `LockedError` while someone else holds the Lock. To Lock only part of a script, use `rig.lock()`:

```python
with Rig.connect("bench3", lock=False) as rig:
    print(rig.get_channels())
    with rig.lock():  # Locked here, released when the block ends
        rig.set_channel(3, "on")
```

Locks nest: the Rig stays Locked until every `rig.lock()` is released, and the Lock taken on connect lasts until `close()`. So `with rig.lock():` inside a script that Locked on connect leaves the Rig Locked after the block. Calling `.release()` on a Lock twice releases it once.

To take the Lock from whoever holds it, after checking with them, pass `take_over=True` to `Rig.connect()` or `rig.lock()`. That's a Takeover. Their script's next change raises `LockedError` naming you, and their `close()` logs a warning instead of releasing your Lock. itch-py never takes over unless you ask.

Closing releases the Lock and leaves the Channels as they are. A script that crashes or loses its connection leaves the Rig Locked. Running it again under the same Holder picks the Lock back up, with the Channels as it left them.

Two scripts run by the same user on the same computer share a Holder, so they share the Lock: either can change the Rig, and closing either releases the Lock for both. Give each its own `holder=` if they must not share.

## Rename a Rig

A new Rig is labelled `itch-` plus the end of its Hardware ID, such as `itch-C02718`. Give it a bench name, up to 64 bytes; the Rig keeps it across reboots, and an empty label restores the default:

```python
rig.set_label("bench3")
```

Or from the command line:

```sh
itch label itch-C02718 bench3
```

`itch label` takes the same names as `Rig.connect()`, including a port or `tcp://host:port`. It Locks the Rig while it renames it, so it fails with the Holder's name if someone else holds the Lock. `itch list` never Locks.

## Put a Rig on Wi-Fi

A Rig joins Wi-Fi once you give it credentials, then advertises itself on the network (see [Rigs on Wi-Fi](#rigs-on-wi-fi)). It keeps them across reboots and never reports the passphrase:

```python
rig.set_wifi("ExampleRigNet", "example-passphrase")
print(rig.status().link)  # Link.CONNECTED once it has joined
rig.clear_wifi()  # back to USB only
```

The SSID is 1 to 32 bytes and the passphrase 8 to 63; anything else raises `ValueError` before itch-py sends it. By default the Rig takes its address from DHCP. To give it a static address, with its prefix and an optional gateway:

```python
from ipaddress import IPv4Address, IPv4Interface

rig.set_address(IPv4Interface("192.0.2.10/24"), gateway=IPv4Address("192.0.2.1"))
rig.use_dhcp()  # back to DHCP
```

The Rig applies exactly what it is told, with no conflict check and no fallback to DHCP. A wrong static address strands the Rig's Wi-Fi until you fix it over USB. itch-py refuses a zero, broadcast or multicast address or gateway, and a /0 prefix, but can't tell whether the address suits your network.

Or from the command line, which Locks the Rig for each command:

```sh
itch wifi set bench3 ExampleRigNet  # asks for the passphrase without echoing it
printf '%s\n' "$PASSPHRASE" | itch wifi set --passphrase-stdin bench3 ExampleRigNet
itch wifi clear bench3
itch address static bench3 192.0.2.10/24 --gateway 192.0.2.1
itch address dhcp bench3
```

These changes need the Lock like any other, so they raise `LockedError` while someone else holds it, and `StorageFaultError` if the Rig couldn't save them, keeping the old setting.

Changing Wi-Fi or the address over the network can cut you off: the Rig leaves and rejoins Wi-Fi after `set_wifi()` or `clear_wifi()`, and moves to its new address about a second after `set_address()` or `use_dhcp()`. The call still succeeds, `close()` stays quiet, and the next call on that connection raises `DisconnectedError` saying to reconnect after the network change. Over USB nothing drops, so provisioning over USB is simplest.

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
dut.resolution.set("1080p")
dut.mode.set("night", encoding=2)
for encoding in dut.mode.all_encodings():  # every Encoding of every Value
    encoding.set()
    ...  # check the DUT

print(dut.mode.get())  # "night"; an alias reads back as the Value it names
print(dut.mode.get_encoding())  # mode="night" Encoding 2 of 2 ["on", "off", "on"]
```

A mistake in a Profile, such as a wrong number of positions, raises a `ProfileError` saying what to fix as soon as the Profile is loaded.

To change several Fields at once, set them inside `with dut.batch():`; they are written together when the block ends. `print(dut)` shows every Field's current Value.

To write a Profile for your own DUT, start with [Writing a Profile](docs/writing-profiles.md) and the [Profile template](docs/profile_template.py).

## Rig logs

The Rig's own log messages are off by default. To see them in your test log, pass a Python logging level. Messages at that level and above go to the `itch.rig` logger as they arrive, even while your script sleeps. They are logged from a thread of itch-py's own, so a log handler may use the Rig:

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
| v0.1.1 | v0.1.1 |
| v0.1.0 | v0.1.0 |

## Development

Uses [uv](https://docs.astral.sh/uv/):

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

The tests run against a real `itch-sim` and the protocol's conformance vectors. They take them from the first of:

1. `ITCH_SIM` (an `itch-sim` binary) and `ITCH_VECTORS` (`vectors-v3.json`).
2. An `itch` checkout, given by `ITCH_REPO` or found next to this one. The sim is built there with `cargo build -p itch-sim`.
3. The `itch` release pinned by `TAG` in `tests/itch_release.py`. The first run downloads its sim and vectors into a local cache and checks them against the release manifest; later runs work offline. CI uses this.

To move to a new `itch` release, bump `TAG` (and `VECTORS_ASSET` if the protocol changed). Add a row to the table under [Releases](#releases) when cutting the itch-py release tested with it.
