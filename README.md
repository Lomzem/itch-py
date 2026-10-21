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

Plug the Rig into the PC over USB. With one Rig plugged in, connect without naming it, and disconnect when done:

```python
from itch import Rig

rig = Rig.connect()
print(rig.label, rig.hardware_id, rig.firmware_version)
rig.disconnect()
```

Or do the same in a `with` block, which disconnects when the block ends, even if the code inside it raises:

```python
with Rig.connect() as rig:
    print(rig.label, rig.hardware_id, rig.firmware_version)
```

Both styles do the same thing; use whichever suits the script. See [Disconnect](#disconnect) for what disconnecting does.

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

A Rig serves at most 4 network connections besides USB, and closes a fifth before answering. itch-py reports that straight away as "Rig at tcp://… closed the connection before replying to Hello; it may already have 4 network connections." Disconnect a script you no longer need, or use USB.

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
rig = Rig.connect("tcp://127.0.0.1:<port>")
```

### Disconnect

Connecting Locks the Rig (see [Sharing a Rig](#sharing-a-rig)). Any of these releases the Lock and frees the port for the next script:

- `rig.disconnect()`;
- leaving a `with Rig.connect(...)` block, including on an exception;
- the script ending without either, normally or on an uncaught exception.

Disconnecting never changes the Channels: the Rig keeps them, so the next script, or a reconnect, finds them as this one left them. Calling `disconnect()` again does nothing, and any read or change on that `rig` then raises `DisconnectedError`.

Connecting again to a Rig the script already has open, on the same USB port or `tcp://` address, just works, as when you re-run a notebook cell that connects. itch-py first disconnects the older connection, releasing its Lock. Using the older variable then raises `DisconnectedError` saying the script connected to the same Rig again, so use the newer one.

## Set and read Channels

Channels are numbered 1 to 16, as on the board. On means the contact is closed, like a DIP switch's ON position.

```python
rig.set(1, 5)  # turn CH1 and CH5 on
rig.clear(3)  # turn CH3 off
rig.write(set=[1, 5], clear=[3])  # turn some on and others off, in one write
rig.set_all()  # turn every Channel on
rig.clear_all()  # turn every Channel off
```

`set`, `clear` and `write` leave every Channel you don't name as it is. `set()` and `clear()` with no Channels raise `ValueError`, so an empty computed list, as in `rig.clear(*failed)`, can never turn every Channel off: that is always `clear_all()`. `write()` raises too if it is given no Channels, or the same Channel in `set` and `clear`.

Read one Channel as `True` or `False`, or all 16 in one read:

```python
rig.clear_all()
rig.set(1, 5)
rig.get(5)  # True
rig.get(3)  # False
print(rig.get_all())  # ChannelState(0x0011, on=[1, 5])
```

`get_all()` shows the state in hex with the Channels that are on. CH1 is the rightmost bit of that hex, so build states from Channel numbers with `ch(...)` (see [Whole Channel states](#whole-channel-states)).

Every read asks the Rig, so it shows what the Rig commands now, and every change is sent, even one that repeats the last.

### Whole Channel states

A Channel state is all 16 Channels as one 16-bit number, as in a failure log or on a bench sheet. `apply` writes one, and `ch()` builds one from Channel numbers:

```python
from itch import ch

rig.apply(ch(1, 5))  # CH1 and CH5 on, every other Channel off
rig.apply(0x6742)  # CH2, CH7, CH9, CH10, CH11, CH14 and CH15 on, the rest off
rig.apply(0x6742, mask=0xFF00)  # write CH9 to CH16 only; CH1 to CH8 stay as they are
rig.apply(ch(9, 10), mask=ch(9, 10, 11, 12))  # CH9 and CH10 on, CH11 and CH12 off
```

The bits of the state outside `mask` are ignored. Binary, such as `0b0110_0111_0100_0010`, works as hex does.

> [!WARNING]
> CH1 is the rightmost bit of a Channel state, and CH16 the leftmost: `0x0001` is CH1 alone and `0x8000` is CH16 alone. Copying switch positions down left to right, CH1 first, gives a backwards number: CH1 and CH2 on is `0x0003`, not `0xC000`. Build states and masks with `ch(...)` rather than by hand: `ch(1, 2) == 0x0003`. Printing a state lists the Channels that are on next to the hex, so a backwards one shows straight away.

The state `get_all()` returns is an `int`, so it compares, masks and applies like one. It also answers which Channels are on without asking the Rig again:

```python
rig.apply(0x6742)
state = rig.get_all()  # ChannelState(0x6742, on=[2, 7, 9, 10, 11, 14, 15])
state == 0x6742  # True
state & ch(1, 2, 3, 4)  # 2: of CH1 to CH4, only CH2 is on
state.get(7)  # True
state.on  # frozenset({2, 7, 9, 10, 11, 14, 15})
rig.apply(state)  # put every Channel back as it was read
```

A state or mask that isn't an `int` from `0x0000` to `0xFFFF`, a `mask` of 0, or a Channel outside 1 to 16 raises `ValueError` before anything is sent.

## Sharing a Rig

Connecting Locks the Rig, so nobody else's script can change it until yours disconnects. Anyone may still read it. The Lock is held under your script's Holder: `user@host` by default, such as `qa@bench-pc`. Pass `holder="..."` to name it yourself, up to 64 bytes:

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
rig = Rig.connect("bench3", lock=False)
print(rig.get_all())
with rig.lock():  # Locked here, released when the block ends
    rig.set(3)
rig.disconnect()
```

Locks nest: the Rig stays Locked until every `rig.lock()` is released, and the Lock taken on connect lasts until the script disconnects. So `with rig.lock():` inside a script that Locked on connect leaves the Rig Locked after the block. Calling `.release()` on a Lock twice releases it once.

To take the Lock from whoever holds it, after checking with them, pass `take_over=True` to `Rig.connect()` or `rig.lock()`. That's a Takeover. Their script's next change raises `LockedError` naming you, and their `disconnect()` logs a warning instead of releasing your Lock. itch-py never takes over unless you ask.

Disconnecting, leaving the `with` block, or the script ending, normally or on an uncaught exception, releases the Lock and leaves the Channels as they are (see [Disconnect](#disconnect)). A script that is killed, or that loses its connection, leaves the Rig Locked. Running it again under the same Holder picks the Lock back up, with the Channels as it left them.

Two scripts run by the same user on the same computer share a Holder, so they share the Lock: either can change the Rig, and disconnecting either releases the Lock for both. Give each its own `holder=` if they must not share.

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

The Rig applies exactly what it is told, with no conflict check and no fallback to DHCP. A wrong static address strands the Rig's Wi-Fi until you fix it over USB. itch-py refuses a zero, broadcast or multicast address, a broadcast or multicast gateway, and a /0 prefix, but can't tell whether the address suits your network. A zero gateway means none, as leaving it out does.

Or from the command line, which Locks the Rig for each command:

```sh
itch wifi set bench3 ExampleRigNet  # asks for the passphrase without echoing it
printf '%s\n' "$PASSPHRASE" | itch wifi set --passphrase-stdin bench3 ExampleRigNet
itch wifi clear bench3
itch address static bench3 192.0.2.10/24 --gateway 192.0.2.1
itch address dhcp bench3
```

These changes need the Lock like any other, so they raise `LockedError` while someone else holds it, and `StorageFaultError` if the Rig couldn't save them, keeping the old setting.

Changing Wi-Fi or the address over the network can cut you off: the Rig leaves and rejoins Wi-Fi after `set_wifi()` or `clear_wifi()`, and moves to its new address about a second after `set_address()` or `use_dhcp()`. The call still succeeds, `disconnect()` stays quiet, and the next call on that connection raises `DisconnectedError` saying to reconnect after the network change. Over USB nothing drops, so provisioning over USB is simplest.

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

Then connect with the Profile. `Rig.connect` returns an `AcmeWidget`, the DUT, which drives both its Fields and the Rig's Channels. In VS Code, the Values autocomplete inside `set("…")`, and a misspelt one is underlined once type checking is on (`"python.analysis.typeCheckingMode": "basic"`):

```python
dut = Rig.connect("bench3", AcmeWidget)  # Rig.connect(profile=AcmeWidget) with one Rig plugged in
dut.resolution.set("1080p")
dut.mode.set("night", encoding=2)
print(dut.mode.get())  # "night"; an alias reads back as the Value it names
print(dut.mode.get_encoding().number)  # 2
print(dut)  # AcmeWidget(resolution="1080p", mode="night" (Encoding 2))
dut.disconnect()
```

Or in a `with` block, which disconnects when it ends:

```python
with Rig.connect("bench3", AcmeWidget) as dut:
    dut.resolution.set("1080p")
```

Disconnecting a DUT disconnects its Rig and releases the Lock, as in [Disconnect](#disconnect).

To set several Fields in one write, pass them to `dut.apply`. Each takes a Value or alias (Encoding 1), a `(Value, number)` tuple to pick an Encoding, or an Encoding itself:

```python
dut.apply(resolution="720p", mode="movie")
dut.apply(mode=("night", 2))  # Encoding 2 of "night"
for encoding in dut.mode.all_encodings():  # every Encoding of every Value
    dut.apply(mode=encoding)
    print(f"dut.apply(mode={(encoding.value, encoding.number)!r})")  # to paste into a report
    ...  # check the DUT
```

`dut.apply` checks every Field before writing, and changes only the Channels of the Fields it names. An unknown Field, Value or Encoding raises `ValueError` saying what the Field accepts, and two Fields that need a shared Channel in different positions raise `BatchConflictError`. Either way, no Channels change.

The DUT has the same Channel verbs as a Rig, so one variable does everything: `dut.set(1, 5)`, `dut.clear(3)`, `dut.write(set=[1, 5], clear=[3])`, `dut.apply(ch(1, 5))`, `dut.set_all()`, `dut.clear_all()`, `dut.get(3)` and `dut.get_all()`. As on a Rig, CH1 is the rightmost bit of a state such as `dut.apply(0x0011)`, so build states with `ch(...)` (see [Whole Channel states](#whole-channel-states)). `dut.apply` takes either a state or Fields, and raises `TypeError` given both. The rest of what a Rig does stays on `dut.rig`, such as `dut.rig.status()` and `dut.rig.set_label("bench3")`.

A mistake in a Profile, such as a wrong number of positions, or a Field named after one of the DUT's own methods, raises a `ProfileError` saying what to fix as soon as the Profile is loaded.

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
| v0.3.0 | v0.3.0 |
| v0.2.0 | v0.3.0 |
| v0.1.1 | v0.1.1 |
| v0.1.0 | v0.1.0 |

### Upgrading to v0.3.0

v0.3.0 breaks scripts written for v0.2.0. The protocol is unchanged, so it works with the same `itch` v0.3.0 sim and firmware. Each old call now raises an error naming its replacement:

| v0.2.0 | v0.3.0 |
| ------ | ------ |
| `rig.set_channel(3, "on")` | `rig.set(3)` |
| `rig.set_channels({1: "on", 3: "off"})` | `rig.write(set=[1], clear=[3])` |
| `rig.get_channel(3) == "on"` | `rig.get(3)` |
| `rig.get_channels()` | `rig.get_all()` |
| `rig.clear()` | `rig.clear_all()` |
| `rig.close()` | `rig.disconnect()` |
| `dut = AcmeWidget(rig)` | `dut = Rig.connect("bench3", AcmeWidget)` |
| `with dut.batch():` and one `.set()` per Field | `dut.apply(resolution="1080p", mode="night")` |

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
