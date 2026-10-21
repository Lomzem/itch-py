# Profile template. See docs/writing-profiles.md for a walk-through.
#
# 1. Copy this file next to your test scripts and rename it after your DUT, e.g. acme_widget.py.
# 2. Rename the class after your DUT, e.g. `class AcmeWidget(Profile):`.
# 3. For each setting of your DUT, copy the "copy this block" Field below and fill it in.
# 4. Delete the example Fields you don't need.
#
# "on" is a DIP switch's ON position (on most switches: pushed right, or towards "1").
# "off" is the other side.
#
# A Field can't be named set, clear, write, apply, set_all, clear_all, get, get_all,
# disconnect or rig, or start with "_": those belong to the DUT itself.
#
# Use it in a test script:
#
#     from itch import Rig
#     from acme_widget import AcmeWidget
#
#     dut = Rig.connect("bench3", AcmeWidget)
#     dut.resolution.set("1080p")
#     dut.apply(refresh="50hz", mode="night")  # change several settings in one write
#     print(dut)  # every setting's current Value
#     dut.disconnect()
#
# or, disconnecting when the block ends:
#
#     with Rig.connect("bench3", AcmeWidget) as dut:
#         dut.resolution.set("1080p")
#
# The Acme Widget is a made-up DUT.

from itch import Profile, alias, field


class AcmeWidget(Profile):
    # ---- copy this block: one per setting -----------------------------------------------
    # resolution: SW1 switches 1 and 2, wired to Channels 1 and 2.
    resolution = field(
        channels=[1, 2],
        values={
            # One "on"/"off" per Channel, in the same order as `channels`.
            "720p": ["on", "off"],
            "1080p": ["off", "on"],
            "4k": ["on", "on"],
        },
    )
    # ---- end of block --------------------------------------------------------------------

    # A setting on a single switch still lists its Channel and positions in [ ].
    standby = field(
        channels=[7],
        values={
            "disabled": ["off"],
            "enabled": ["on"],
        },
    )

    # Two settings on the same switch: CH3 sets both the picture and the tone.
    picture = field(
        channels=[3],
        values={
            "black": ["off"],
            "bars": ["on"],
        },
    )
    tone = field(
        channels=[3],
        values={
            "silent": ["off"],
            "1khz": ["on"],
        },
    )

    # A switch that is also part of a bigger setting: CH4 is `refresh` and part of `mode`.
    refresh = field(
        channels=[4],
        values={
            "60hz": ["off"],
            "50hz": ["on"],
        },
    )

    mode = field(
        channels=[4, 5, 6],
        values={
            "cinema": ["off", "off", "off"],
            "sport": ["off", "off", "on"],
            # The DUT accepts "night" in three ways (Encodings), one per line.
            # set("night") uses the first one unless you pick another.
            "night": [
                ["on", "off", "off"],
                ["on", "off", "on"],
                ["on", "on", "off"],
            ],
            # Another name for "cinema" (an alias).
            "movie": alias("cinema"),
        },
    )
