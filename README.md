# itch-py

Control a DUT's DIP switches with Python and an [itch Rig](https://github.com/Lomzem/itch).
A DUT is the device under test. Each Rig has 16 Channels.

## Install

Install Python 3.11 or later. Install Git.
Use the commands below to install v0.3.0 in a virtual environment.

Linux and macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install "itch @ git+https://github.com/Lomzem/itch-py.git@v0.3.0"
```

Windows Command Prompt:

```bat
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install "itch @ git+https://github.com/Lomzem/itch-py.git@v0.3.0"
```

Use the same terminal to run `itch` and your Python scripts.

## Connect to a Rig

Connect one Rig to your computer with USB. List the available Rigs:

```sh
itch list
```

Run this Python script:

```python
from itch import Rig

with Rig.connect() as rig:
    print(rig.label, rig.hardware_id, rig.firmware_version)
    rig.set(1, 5)  # Turn Channels 1 and 5 on.
    rig.clear(3)  # Turn Channel 3 off.
    print(rig.get(5))  # True
    print(rig.get_all())
```

The `with` block Locks the Rig and disconnects when the block ends, including after an exception.
Disconnecting releases the Lock and keeps the Channel states.
Without a `with` block, call `rig.disconnect()` when you finish.

For several Rigs, pass a label, Hardware ID or USB port to `Rig.connect()`.
Use a label from `itch list`:

```python
with Rig.connect("bench3") as rig:
    print(rig.get_all())
```

On Linux, your account needs access to the USB port.
Join its group, usually `dialout` on Debian and Ubuntu or `uucp` on Arch. Then log in again.

## Set and read Channels

Channels are numbered 1 to 16. On means the contact is closed.
This is the same as a DIP switch in its ON position.
Every read gets the current state from the Rig.
Use these commands inside a connected Rig's `with` block:

```python
rig.set(1, 5)  # Turn Channels 1 and 5 on.
rig.clear(3)  # Turn Channel 3 off.
rig.write(set=[1, 5], clear=[3])  # Change these Channels in one write.
rig.set_all()  # Turn all Channels on.
rig.clear_all()  # Turn all Channels off.
rig.get(5)  # Read one Channel as True or False.
rig.get_all()  # Read all 16 Channels.
```

`set()`, `clear()` and `write()` change only the Channels you name. They reject calls with no Channels.
`write()` also rejects a Channel in both lists.

Use `ch()` to build a complete Channel state or a mask:

```python
from itch import ch

rig.apply(ch(1, 5))  # Turn Channels 1 and 5 on. Turn all others off.
rig.apply(ch(9, 10), mask=ch(9, 10, 11, 12))  # Change only Channels 9 to 12.
state = rig.get_all()
print(state.on)  # The Channels that are on.
rig.apply(state)  # Restore the saved state.
```

Channel 1 is the rightmost bit. `ch(1, 2)` is `0x0003`.
States must be integers from `0x0000` to `0xFFFF`. A mask cannot be zero.

## Use a Profile

A Profile gives names to DUT settings. This example uses a made-up DUT:

```python
from itch import Profile, Rig, field


class AcmeWidget(Profile):
    resolution = field(
        channels=[1, 2],
        values={
            "720p": [1, 0],
            "1080p": [0, 1],
        },
    )


with Rig.connect(profile=AcmeWidget) as dut:
    dut.resolution.set("1080p")
    print(dut.resolution.get())
    dut.apply(resolution="720p")
```

Each Value lists one position for each Channel in its Field, in `channels` order: 1 for on, 0 for off.
`dut.apply()` checks all named Fields before it changes their Channels in one write.
Invalid Values or conflicting Fields leave all Channels unchanged.

The DUT also has the Rig's Channel commands.
Use `dut.rig` for Rig settings, such as `dut.rig.set_label("bench3")`.

See the [Profile guide](docs/writing-profiles.md) for Aliases, Encodings and editor completion.
Start your own Profile with the [template](docs/profile_template.py).

## Share a Rig

`Rig.connect()` takes a Lock under `user@host` by default. Other Holders can read the Rig but cannot change it.
If another Holder has the Lock, connecting raises `LockedError` with their name.

- Pass `lock=False` to connect without a Lock.
- Connect with `lock=False`, then use `with rig.lock():` to hold a Lock for part of a script.
- Pass a distinct `holder` to each script that must have its own Lock.
- After agreement with the current Holder, pass `take_over=True` to take their Lock.

Two scripts with the same Holder share the Lock. Disconnecting either script releases it for both.
A killed script or a lost connection can leave the Rig Locked.
Reconnect with the same Holder to use that Lock again.

## Set the label and Wi-Fi

Use USB for network changes. A network change can disconnect a network connection.
The Rig saves its label and Wi-Fi settings across restarts.

```python
from getpass import getpass

from itch import Rig

with Rig.connect() as rig:
    rig.set_label("bench3")
    rig.set_wifi(input("Wi-Fi name: "), getpass("Wi-Fi password: "))
```

`rig.clear_wifi()` removes the Wi-Fi settings. `rig.status()` reports the connection state.

To connect over Wi-Fi, use the Rig's label or Hardware ID.
itch-py checks USB first, then searches the network with mDNS for 3 seconds.
Give each Rig a distinct label. `Rig.connect()` without a name checks USB only.

`itch list` includes Rigs on the network. To bypass mDNS, pass a `tcp://` address to `Rig.connect()`.
Each Rig accepts up to four network connections in addition to USB.

## Try without hardware

Download the [itch v0.3.0 simulator](https://github.com/Lomzem/itch/releases/tag/v0.3.0) for your system.
Open a terminal in the download folder.

Linux:

```sh
chmod +x itch-sim-linux-x86_64
./itch-sim-linux-x86_64 --bind 127.0.0.1:7878
```

Windows Command Prompt:

```bat
itch-sim-windows-x86_64.exe --bind 127.0.0.1:7878
```

Keep the simulator running. Run this script in your Python environment:

```python
from itch import Rig

with Rig.connect("tcp://127.0.0.1:7878") as rig:
    rig.set(1, 5)
    print(rig.get_all())  # ChannelState(0x0011, on=[1, 5])
```

## Releases

Use the matching firmware or simulator release:

| itch-py | Tested itch release |
| --- | --- |
| v0.3.0 | v0.3.0 |
| v0.2.0 | v0.3.0 |
| v0.1.1 | v0.1.1 |
| v0.1.0 | v0.1.0 |

v0.3.0 changes the Python API. It uses the same protocol as v0.2.0.
See the [upgrade examples](https://github.com/Lomzem/itch-py/blob/v0.3.0/README.md#upgrading-to-v030) before you update an older script.

## Development

Install [uv](https://docs.astral.sh/uv/). Run these commands in the repository:

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

Tests use `ITCH_SIM` and `ITCH_VECTORS` if set, or build the simulator from a sibling `itch` checkout.
Set `ITCH_REPO` to use a checkout elsewhere.
Without a checkout, tests download and verify the release in `tests/itch_release.py`.
Update its `TAG` and this compatibility table when the tested itch release changes.
