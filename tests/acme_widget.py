"""A Profile for the Acme Widget, a made-up DUT."""

from itch import Profile, alias, field


class AcmeWidget(Profile):
    resolution = field(
        channels=[1, 2],
        values={
            "720p": ["on", "off"],
            "1080p": ["off", "on"],
            "4k": ["on", "on"],
        },
    )

    mode = field(
        channels=[4, 5, 6],
        values={
            "cinema": ["off", "off", "off"],
            "sport": ["off", "off", "on"],
            "night": [
                ["on", "off", "off"],
                ["on", "off", "on"],
                ["on", "on", "off"],
            ],
            "movie": alias("cinema"),
        },
    )
