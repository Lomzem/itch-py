"""A Profile for the Acme Widget, a made-up DUT."""

from itch import Profile, alias, field


class AcmeWidget(Profile):
    resolution = field(
        channels=[1, 2],
        values={
            "720p": [1, 0],
            "1080p": [0, 1],
            "4k": [1, 1],
        },
    )

    # One switch, two meanings: CH3 sets both the picture and the tone.
    picture = field(
        channels=[3],
        values={
            "black": [0],
            "bars": [1],
        },
    )
    tone = field(
        channels=[3],
        values={
            "silent": [0],
            "1khz": [1],
        },
    )

    # CH4 is also part of `mode`.
    refresh = field(
        channels=[4],
        values={
            "60hz": [0],
            "50hz": [1],
        },
    )

    mode = field(
        channels=[4, 5, 6],
        values={
            "cinema": [0, 0, 0],
            "sport": [0, 0, 1],
            "night": [
                [1, 0, 0],
                [1, 0, 1],
                [1, 1, 0],
            ],
            "movie": alias("cinema"),
        },
    )
