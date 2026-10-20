# Prints the message a QA engineer would see for each common Profile mistake.
# PROTOTYPE. Run:  python show_errors.py

from itch_prototype import BatchConflictError, Profile, ProfileError, Rig, alias, field


def attempt(title: str, make) -> None:
    print(f"\n## {title}")
    try:
        make()
        print("   (no error)")
    except (ProfileError, ValueError, BatchConflictError) as e:
        print(f"   {type(e).__name__}: {e}")


def wrong_count():
    class Widget(Profile):
        resolution = field(channels=[1, 2], values={"720p": ["on"], "1080p": ["off", "on"]})


def bad_word():
    class Widget(Profile):
        resolution = field(channels=[1, 2], values={"720p": ["on", "of"]})  # type: ignore[dict-item]  # VS Code flags this too


def batch_conflict():
    class Widget(Profile):
        refresh = field(channels=[4], values={"60hz": ["off"], "50hz": ["on"]})
        mode = field(channels=[4, 5], values={"cinema": ["off", "off"], "night": ["on", "off"]})

    rig = Rig.connect()
    dut = Widget(rig)
    with rig.session():
        with dut.batch():
            dut.refresh.set("60hz")
            dut.mode.set("night")


def encoding_wrong_count():
    class Widget(Profile):
        mode = field(channels=[4, 5], values={"night": [["on", "off"], ["on"]]})


def mixed_encodings():
    class Widget(Profile):
        mode = field(channels=[4, 5], values={"night": ["on", ["on", "off"]]})  # type: ignore


def same_encoding_two_values():
    class Widget(Profile):
        mode = field(channels=[4, 5], values={"cinema": ["off", "off"], "movie": ["off", "off"]})


def alias_to_nothing():
    class Widget(Profile):
        mode = field(channels=[4, 5], values={"cinema": ["off", "off"], "movie": alias("cinemaa")})


def alias_to_alias():
    class Widget(Profile):
        mode = field(channels=[4, 5], values={"cinema": ["off", "off"], "movie": alias("cinema"), "film": alias("movie")})


def encoding_out_of_range():
    class Widget(Profile):
        mode = field(channels=[4, 5], values={"night": [["on", "off"], ["on", "on"]]})

    rig = Rig.connect()
    with rig.session():
        Widget(rig).mode.set("night", encoding=3)


def no_such_channel():
    class Widget(Profile):
        hdr = field(channels=[17], values={"off": ["off"], "on": ["on"]})


def same_positions():
    class Widget(Profile):
        resolution = field(channels=[1, 2], values={"720p": ["on", "off"], "4k": ["on", "off"]})


def typo_in_script():
    class Widget(Profile):
        resolution = field(channels=[1, 2], values={"720p": ["on", "off"], "1080p": ["off", "on"]})

    rig = Rig.connect()
    with rig.session():
        Widget(rig).resolution.set("1080")  # type: ignore[arg-type]  # VS Code flags this too


def unknown_readback():
    class Widget(Profile):
        resolution = field(channels=[1, 2], values={"720p": ["on", "off"], "1080p": ["off", "on"]})

    rig = Rig.connect()
    with rig.session():
        rig.set_channel(1, "on")
        rig.set_channel(2, "on")
        print("   reading back:", Widget(rig).resolution.get())


def not_a_list():
    class Widget(Profile):
        resolution = field(channels=[1, 2], values={"720p": "on off"})  # type: ignore[dict-item]


def channel_out_of_range():
    rig = Rig.connect()
    with rig.session():
        rig.set_channel(17, "on")


attempt("Value has the wrong number of positions", wrong_count)
attempt("Positions written as one string instead of a list", not_a_list)
attempt("Typo in a position", bad_word)
attempt("Channel number out of range", no_such_channel)
attempt("Two Values with the same positions", same_positions)
attempt("Misspelled Value in a QA script", typo_in_script)
attempt("Channels match no Value when reading back", unknown_readback)
attempt("Batch sets a shared Channel two ways", batch_conflict)
attempt("An Encoding has the wrong number of positions", encoding_wrong_count)
attempt("Single positions mixed with Encoding lists", mixed_encodings)
attempt("Two Values with the same Encoding (meant an alias?)", same_encoding_two_values)
attempt("Alias points at a misspelled Value", alias_to_nothing)
attempt("Alias points at another alias", alias_to_alias)
attempt("Encoding number too big", encoding_out_of_range)
attempt("Setting a Channel that doesn't exist", channel_out_of_range)
