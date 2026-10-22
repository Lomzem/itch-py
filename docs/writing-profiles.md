# Writing a Profile

A Profile lets a test script say `dut.resolution.set("1080p")` instead of "turn Channel 1 off and Channel 2 on". You write one Profile per DUT model, once, by copying a template and filling in the DUT's switch table. You don't need to know Python beyond what this page shows.

The examples use the Acme Widget, a made-up DUT.

## Updating an existing Profile

Profile positions now use integers. Replace `"on"` with `1` and `"off"` with `0` inside each Encoding, including nested lists. Older string positions raise `ProfileError` when the Profile loads. Keep Value names and Alias names as strings.

`Encoding.positions` also returns numeric lists, such as `[1, 0]`. Update any script that compares those positions with strings. Calls such as `dut.resolution.set("1080p")` keep the same form.

## Before you start

You need:

- **The DUT's switch table**, from its manual or schematic: which switches set which setting, and the ON/OFF pattern for each choice.
- **The Rig's wiring**: which Rig Channel (CH1 to CH16, as printed on the board) stands in for which DUT switch.
- **VS Code with the Python extension.** Turn on type checking so typos get a red underline: open Settings (JSON) and add

  ```json
  "python.analysis.typeCheckingMode": "basic"
  ```

  The [Ruff extension](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff) is worth adding too (see [A Value listed twice](#a-value-listed-twice)).

## Start from the template

Copy [`profile_template.py`](profile_template.py) next to your test scripts and rename it after your DUT, for example `acme_widget.py`. Then:

1. Rename the class after your DUT: `class AcmeWidget(Profile):`.
2. For each setting of the DUT, copy the block marked "copy this block" and fill it in (next section).
3. Delete the example settings you don't need.

## Write one setting

Each setting of the DUT is a **Field**. This block is one Field:

```python
    resolution = field(
        channels=[1, 2],
        values={
            "720p": [1, 0],
            "1080p": [0, 1],
            "4k": [1, 1],
        },
    )
```

Fill in three things:

- **The Field's name**, before the `=`: here `resolution`. Scripts use it as `dut.resolution`. Use lowercase letters, digits and `_`, starting with a letter: `resolution`, `audio_out`, `sw2_mode`. No spaces or dashes, and none of the [names a DUT keeps for itself](#names-a-field-cant-have).
- **`channels`**: the Rig Channels the setting uses, in square brackets, separated by commas.
- **`values`**: one line per choice, called a **Value**. The name goes in quotes, then a colon, then one `1` (on) or `0` (off) per Channel, **in the same order as `channels`**. Above, `"1080p": [0, 1]` means CH1 off and CH2 on. A Value's name can be anything in quotes, spaces included.

Keep the indentation, the commas at the end of each line, and the brackets as they are in the block.

### On and off

`1` is the DIP switch's **ON** position: on most switches that is pushed to the right, or towards the side marked `1` or `ON`. `0` is the other side. If the DUT's table writes `ON`/`OFF`, write `ON` as `1` and `OFF` as `0`. Only the numbers `1` and `0` are accepted: not `"on"`, `True` or `2`.

The Rig doesn't care which way the switch is drawn in the manual. If the DUT behaves the opposite of what you expect, check the switch table's ON side before changing the Profile.

### Names a Field can't have

A DUT has a few methods of its own, alongside its Fields: `set`, `clear`, `write`, `apply`, `set_all`, `clear_all`, `get`, `get_all`, `disconnect` and `rig`. A Field can't take one of those names, or a name starting with `_`. Such a Field raises a `ProfileError` as soon as the Profile loads:

```
itch._errors.ProfileError: AcmeWidget.set: Field `set` clashes with a DUT method; give it another name.
```

Rename the Field, for example to `setting` or `sw1_set`. The list never grows: new Rig features go on `dut.rig`, never on the DUT itself, so a Profile that loads today keeps loading after an itch-py upgrade. Names such as `input`, `output`, `format`, `mode`, `state`, `status` and `label` are all fine.

### A setting on one switch

It still uses square brackets, with one Channel and one `1` or `0`:

```python
    standby = field(
        channels=[7],
        values={
            "disabled": [0],
            "enabled": [1],
        },
    )
```

### A setting on many switches

A Value's list can span several lines. For a Field on all 16 Channels, write four Channels per line, one line per Bank of four switches, and label the lines once in the first Value:

```python
    # fmt: off
    routing = field(
        channels=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
        values={
            "passthrough": [
                0, 0, 0, 0,  # SW1: CH1 to CH4
                0, 0, 0, 0,  # SW2: CH5 to CH8
                0, 0, 0, 0,  # SW3: CH9 to CH12
                0, 0, 0, 0,  # SW4: CH13 to CH16
            ],
            "loopback": [
                1, 0, 0, 0,
                0, 1, 0, 0,
                0, 0, 1, 0,
                0, 0, 0, 1,
            ],
            "split": [
                1, 1, 0, 0,
                1, 1, 0, 0,
                0, 0, 1, 1,
                0, 0, 1, 1,
            ],
        },
    )
    # fmt: on
```

The Profile interprets the 16 numbers in `channels` order, whatever the line breaks: `"loopback"` turns on CH1, CH6, CH11 and CH16. The `# fmt: off` and `# fmt: on` lines preserve the grouping when an editor formats on save with Ruff or Black. Without such a formatter you can leave them out.

## Check the Profile

Run the file (`python acme_widget.py`, or the Run button in VS Code). If nothing is printed, the Profile is fine. If something is wrong, you get a `ProfileError` that names the Field and says what to fix, for example:

```
itch._errors.ProfileError: AcmeWidget.resolution: "720p" has 1 position, but resolution uses 2 Channels (CH1, CH2). Give one 1 or 0 per Channel, in that order.
```

Common ones:

| Message says | Fix |
| ------------ | --- |
| `has 1 position, but … uses 2 Channels` | Give exactly one `1` or `0` per Channel. |
| `has "on" for CH2. Use 1 for on or 0 for off.` | Write `1` for on and `0` for off, without quotes. |
| `has 2 for CH2. Use 1 for on or 0 for off.` | A typo in a position. |
| `Channel 17 doesn't exist` | Channels are numbered 1 to 16. |
| `"720p" and "4k" are both [1, 0]` | Two Values have the same positions. Fix one, or make one an alias. |
| `the Value "720p" is listed twice` | See [A Value listed twice](#a-value-listed-twice). |
| `the Value name 720 needs quotes` | Write `"720"`, not `720`. |
| ``Field `set` clashes with a DUT method`` | Rename the Field. See [Names a Field can't have](#names-a-field-cant-have). |

## Use it in a script

Connect with the Profile, drive the DUT, and disconnect when done:

```python
from itch import Rig

from acme_widget import AcmeWidget

dut = Rig.connect("tcp://127.0.0.1:<port>", AcmeWidget)  # see the README to connect
dut.resolution.set("1080p")
dut.mode.set("night")
print(dut)  # AcmeWidget(resolution="1080p", ..., mode="night" (Encoding 1))
print(dut.resolution.get())  # "1080p"
dut.disconnect()
```

Or do the same in a `with` block, which disconnects when the block ends, even if the code inside it raises:

```python
with Rig.connect("tcp://127.0.0.1:<port>", AcmeWidget) as dut:
    dut.resolution.set("1080p")
```

Both styles work the same. Disconnecting releases the Rig's Lock, so a colleague's script can use it, and leaves the Channels as they are. A script that ends without disconnecting, normally or on an uncaught exception, releases the Lock as it exits.

- `dut.<field>.set("<value>")` changes a setting. In VS Code, type `set("` and the Values appear in a list; a misspelt one is underlined in red.
- `dut.<field>.get()` reads the setting back.
- `print(dut)` shows every Field's current Value on one line, handy for a test log. A Field whose Channels match none of its Values shows its positions and `(no Value)`.

The DUT also drives Channels by number, with the same calls as a Rig: `dut.set(1, 5)`, `dut.clear(3)`, `dut.get(3)`, `dut.get_all()` and the rest (see the README's [Set and read Channels](../README.md#set-and-read-channels)). The Rig itself is `dut.rig`, for everything else a Rig does, such as `dut.rig.status()`.

## A Value the DUT accepts in several ways

Some DUTs accept the same choice through several switch patterns, for example when one switch doesn't matter for that choice. Each pattern is an **Encoding**. List them one per line, inside an extra pair of square brackets:

```python
    mode = field(
        channels=[4, 5, 6],
        values={
            "cinema": [0, 0, 0],
            "night": [
                [1, 0, 0],
                [1, 0, 1],
                [1, 1, 0],
            ],
        },
    )
```

`dut.mode.set("night")` uses the first Encoding. To test each one, so a broken one can't hide behind a working one:

```python
for encoding in dut.mode.encodings("night"):  # every Encoding of "night"
    dut.apply(mode=encoding)
    print(f"dut.apply(mode={(encoding.value, encoding.number)!r})")  # dut.apply(mode=('night', 2))
    ...  # check the DUT here

for encoding in dut.mode.all_encodings():  # every Encoding of every Value
    dut.apply(mode=encoding)
    ...

dut.apply(mode=("night", 3))  # re-run one Encoding from a failure report
dut.mode.set("night", encoding=3)  # the same, for one Field
```

The printed line can be pasted straight into a script to re-run that Encoding.

## Another name for a Value

If people call one choice by two names, add the second as an **alias** rather than repeating the positions:

```python
            "cinema": [0, 0, 0],
            "movie": alias("cinema"),
```

`set("movie")` sets the same switches as `set("cinema")`, and `get()` reads back `"cinema"`. Add `alias` to the import line at the top: `from itch import Profile, alias, field`.

## Settings that share a switch

Two Fields may use the same Channel, for example when one switch has two meanings, or when a switch is a setting of its own and also part of a bigger one:

```python
    # CH3 sets both the picture and the tone.
    picture = field(channels=[3], values={"black": [0], "bars": [1]})
    tone = field(channels=[3], values={"silent": [0], "1khz": [1]})

    # CH4 is `refresh`, and also the first switch of `mode` (channels=[4, 5, 6], above).
    refresh = field(channels=[4], values={"60hz": [0], "50hz": [1]})
```

Setting one changes the other: after `dut.picture.set("bars")`, `dut.tone.get()` is `"1khz"`.

## Change several settings together

To change several Fields at the same moment, pass them all to `dut.apply`:

```python
dut.apply(resolution="4k", refresh="50hz", mode="night")  # mode agrees with refresh on CH4
```

All their Channels change in one write, and Channels of Fields you don't name stay as they are. Each Field takes a Value or alias (Encoding 1), a `(Value, number)` tuple such as `mode=("night", 2)`, or an Encoding from `encodings()` or `all_encodings()`.

`dut.apply` checks every Field before writing anything, so one typo doesn't leave the DUT half-changed. An unknown Field, Value or Encoding raises `ValueError` saying what it accepts. If two Fields need a shared Channel in different positions, the write is refused and **no Channels change**:

```python
dut.apply(refresh="60hz", mode="night")  # refresh needs CH4 off, night needs it on
```

```
itch._errors.BatchConflictError: CH4: refresh="60hz" needs off, but mode="night" needs on. Set only one of them, or pick Values that agree. No Channels were changed.
```

## Pitfalls

### A Value listed twice

If you copy a line and forget to rename it, Python quietly keeps only the last one:

```python
    resolution = field(
        channels=[1, 2],
        values={
            "720p": [1, 0],
            "720p": [0, 1],  # meant "1080p"
        },
    )
```

itch catches this when the Profile loads (`the Value "720p" is listed twice`). With the Ruff extension, VS Code also underlines it as you type (rule F601). itch can only check a Profile saved in a `.py` file, not one typed into a Python prompt.

### Keep `values` inside `field(...)`

Write the `values={...}` dict directly inside `field(...)`, as in the template. If you move it into a variable of its own, VS Code no longer knows the Value names, so they stop appearing in the list and typos stop being underlined.

### Setting a Value with `=`

Use `dut.mode.set("cinema")`, or `dut.apply(mode="cinema")`. `dut.mode = "cinema"` raises an error that points you to `set()`.

## Where to keep Profiles

Keep your Profiles wherever your team keeps its test scripts, such as a private test repository. A Profile is a plain `.py` file and needs nothing beyond `itch` itself. Don't add real DUT Profiles to the public itch-py repository.
