# Writing a Profile

A Profile lets a test script say `dut.resolution.set("1080p")` instead of "turn Channel 1 off and Channel 2 on". You write one Profile per DUT model, once, by copying a template and filling in the DUT's switch table. You don't need to know Python beyond what this page shows.

The examples use the Acme Widget, a made-up DUT.

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
            "720p": ["on", "off"],
            "1080p": ["off", "on"],
            "4k": ["on", "on"],
        },
    )
```

Fill in three things:

- **The Field's name**, before the `=`: here `resolution`. Scripts use it as `dut.resolution`. Use lowercase letters, digits and `_`, starting with a letter: `resolution`, `audio_out`, `sw2_mode`. No spaces or dashes.
- **`channels`**: the Rig Channels the setting uses, in square brackets, separated by commas.
- **`values`**: one line per choice, called a **Value**. The name goes in quotes, then a colon, then one `"on"` or `"off"` per Channel, **in the same order as `channels`**. Above, `"1080p": ["off", "on"]` means CH1 off and CH2 on. A Value's name can be anything in quotes, spaces included.

Keep the indentation, the commas at the end of each line, and the brackets as they are in the block.

### On and off

`"on"` is the DIP switch's **ON** position: on most switches that is pushed to the right, or towards the side marked `1` or `ON`. `"off"` is the other side. If the DUT's table writes `1`/`0`, then `1` is `"on"`.

The Rig doesn't care which way the switch is drawn in the manual. If the DUT behaves the opposite of what you expect, check the switch table's ON side before changing the Profile.

### A setting on one switch

It still uses square brackets, with one Channel and one position:

```python
    standby = field(
        channels=[7],
        values={
            "disabled": ["off"],
            "enabled": ["on"],
        },
    )
```

## Check the Profile

Run the file (`python acme_widget.py`, or the Run button in VS Code). If nothing is printed, the Profile is fine. If something is wrong, you get a `ProfileError` that names the Field and says what to fix, for example:

```
itch._errors.ProfileError: AcmeWidget.resolution: "720p" has 1 position, but resolution uses 2 Channels (CH1, CH2). Give one on/off per Channel, in that order.
```

Common ones:

| Message says | Fix |
| ------------ | --- |
| `has 1 position, but … uses 2 Channels` | Give exactly one `"on"`/`"off"` per Channel. |
| `has "of" for CH2. Use "on" or "off".` | A typo in a position. |
| `Channel 17 doesn't exist` | Channels are numbered 1 to 16. |
| `"720p" and "4k" are both ["on", "off"]` | Two Values have the same positions. Fix one, or make one an alias. |
| `the Value "720p" is listed twice` | See [A Value listed twice](#a-value-listed-twice). |
| `the Value name 720 needs quotes` | Write `"720"`, not `720`. |

## Use it in a script

```python
from itch import Rig

from acme_widget import AcmeWidget

with Rig.connect("tcp://127.0.0.1:<port>") as rig:  # see the README to connect
    dut = AcmeWidget(rig)
    with rig.session():  # hold the Rig while changing its Channels
        dut.resolution.set("1080p")
        dut.mode.set("night")
    print(dut)  # AcmeWidget(resolution="1080p", ..., mode="night" (Encoding 1))
    print(dut.resolution.get())  # "1080p"
```

- `with rig.session():` reserves the Rig for your script. Every `set()` must be inside it; reading with `get()` or `print(dut)` works anywhere.
- `dut.<field>.set("<value>")` changes a setting. In VS Code, type `set("` and the Values appear in a list; a misspelt one is underlined in red.
- `dut.<field>.get()` reads the setting back.
- `print(dut)` shows every Field's current Value on one line, handy for a test log. A Field whose Channels match none of its Values shows its positions and `(no Value)`.

## A Value the DUT accepts in several ways

Some DUTs accept the same choice through several switch patterns, for example when one switch doesn't matter for that choice. Each pattern is an **Encoding**. List them one per line, inside an extra pair of square brackets:

```python
    mode = field(
        channels=[4, 5, 6],
        values={
            "cinema": ["off", "off", "off"],
            "night": [
                ["on", "off", "off"],
                ["on", "off", "on"],
                ["on", "on", "off"],
            ],
        },
    )
```

`dut.mode.set("night")` uses the first Encoding. To test each one, so a broken one can't hide behind a working one:

```python
    with rig.session():
        for encoding in dut.mode.encodings("night"):  # every Encoding of "night"
            encoding.set()
            print("testing", encoding)  # mode="night" Encoding 2 of 3 ["on", "off", "on"]
            ...  # check the DUT here

        for encoding in dut.mode.all_encodings():  # every Encoding of every Value
            encoding.set()
            ...

        dut.mode.set("night", encoding=3)  # re-run one Encoding from a failure report
```

## Another name for a Value

If people call one choice by two names, add the second as an **alias** rather than repeating the positions:

```python
            "cinema": ["off", "off", "off"],
            "movie": alias("cinema"),
```

`set("movie")` sets the same switches as `set("cinema")`, and `get()` reads back `"cinema"`. Add `alias` to the import line at the top: `from itch import Profile, alias, field`.

## Settings that share a switch

Two Fields may use the same Channel, for example when one switch has two meanings, or when a switch is a setting of its own and also part of a bigger one:

```python
    # CH3 sets both the picture and the tone.
    picture = field(channels=[3], values={"black": ["off"], "bars": ["on"]})
    tone = field(channels=[3], values={"silent": ["off"], "1khz": ["on"]})

    # CH4 is `refresh`, and also the first switch of `mode`.
    refresh = field(channels=[4], values={"60hz": ["off"], "50hz": ["on"]})
    mode = field(channels=[4, 5, 6], values={...})
```

Setting one changes the other: after `dut.picture.set("bars")`, `dut.tone.get()` is `"1khz"`.

## Change several settings together

To change several Fields at the same moment, put the `set()` calls in a batch:

```python
    with rig.session():
        with dut.batch():  # nothing changes until the block ends
            dut.resolution.set("4k")
            dut.refresh.set("50hz")
            dut.mode.set("night")  # agrees with refresh on CH4, so this is fine
```

When the block ends, all the Channels change in one go. Setting the same Field twice in a batch keeps the last Value.

If two Fields need a shared Channel in different positions, the batch is refused and **no Channels change**:

```python
        with dut.batch():
            dut.refresh.set("60hz")  # CH4 off
            dut.mode.set("night")  # CH4 on
```

```
itch._errors.BatchConflictError: CH4: refresh="60hz" needs off, but mode="night" needs on. Set only one of them in a batch, or pick Values that agree. No Channels were changed.
```

## Pitfalls

### A Value listed twice

If you copy a line and forget to rename it, Python quietly keeps only the last one:

```python
        values={
            "720p": ["on", "off"],
            "720p": ["off", "on"],  # meant "1080p"
        },
```

itch catches this when the Profile loads (`the Value "720p" is listed twice`). With the Ruff extension, VS Code also underlines it as you type (rule F601). itch can only check a Profile saved in a `.py` file, not one typed into a Python prompt.

### Keep `values` inside `field(...)`

Write the `values={...}` dict directly inside `field(...)`, as in the template. If you move it into a variable of its own, VS Code no longer knows the Value names, so they stop appearing in the list and typos stop being underlined.

### Setting a Value with `=`

Use `dut.mode.set("cinema")`. `dut.mode = "cinema"` raises an error that points you to `set()`.

## Where to keep Profiles

Keep your Profiles wherever your team keeps its test scripts, such as a private test repository. A Profile is a plain `.py` file and needs nothing beyond `itch` itself. Don't add real DUT Profiles to the public itch-py repository.
