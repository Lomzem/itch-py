# A Profile for the Acme Widget.
# PROTOTYPE. "Acme Widget" is a made-up DUT.

from itch_prototype import Profile, alias, field


class AcmeWidget(Profile):
    # Each Value lists one on/off per Channel, in the same order as `channels`.
    resolution = field(channels=[1, 2], values={
        "720p":  ["on",  "off"],
        "1080p": ["off", "on"],
        "4k":    ["on",  "on"],
    })

    # One switch, two meanings: CH3 sets both the picture and the tone.
    picture = field(channels=[3], values={
        "black": ["off"],
        "bars":  ["on"],
    })
    tone = field(channels=[3], values={
        "silent": ["off"],
        "1khz":   ["on"],
    })

    refresh = field(channels=[4], values={
        "60hz": ["off"],
        "50hz": ["on"],
    })

    # CH4 is also part of `mode`. A Value the DUT accepts in several ways
    # lists each Encoding on its own line; set() uses the first unless told otherwise.
    mode = field(channels=[4, 5, 6], values={
        "cinema": ["off", "off", "off"],
        "sport":  ["off", "off", "on"],
        "eco": [
            ["off", "on", "off"],
            ["off", "on", "on"],
        ],
        "night": [
            ["on", "off", "off"],
            ["on", "off", "on"],
            ["on", "on",  "off"],
            ["on", "on",  "on"],
        ],
        "movie": alias("cinema"),   # another name for "cinema"
    })
