# A QA script using the Acme Widget Profile. PROTOTYPE.
# Run:  python script.py
#
# Try in VS Code: delete "night" and type " inside set( ... ) to see the
# Values listed, or misspell a Value and look for the red squiggle.

from itch_prototype import Rig
from acme_widget import AcmeWidget

rig = Rig.connect()
dut = AcmeWidget(rig)

with rig.session():                # hold the Rig's Lease while changing Channels
    dut.resolution.set("1080p")
    dut.mode.set("night")          # Encoding 1 of night
    print(dut)

    # Test every Encoding of one Value, so a broken one can't hide behind a working one.
    for enc in dut.mode.encodings("night"):
        enc.set()
        print("testing", enc)
        # ... check the DUT here ...

    # Or every Encoding of every Value:
    for enc in dut.mode.all_encodings():
        enc.set()
        print("testing", enc)

    # Re-run one Encoding from a failure report:
    dut.mode.set("night", encoding=3)
    print("now", dut.mode.get_encoding())

    # An alias reads back as the Value it stands for:
    dut.mode.set("movie")
    print("mode is", dut.mode.get())

    # CH3 has two meanings, so picture and tone always agree:
    dut.picture.set("bars")
    print("tone is", dut.tone.get())

    with dut.batch():              # these changes happen together when the block ends
        dut.resolution.set("4k")
        dut.refresh.set("50hz")
        dut.mode.set("night")      # agrees with refresh on CH4, so this is fine
    print(dut)

    # Channel-level access still works alongside a Profile:
    rig.set_channel(16, "on")
    print(rig.get_channel(16))          # "on"
    print(rig.get_channels([1, 2, 16])) # {1: ..., 2: ..., 16: "on"}
    print(rig.get_channels())           # all 16
    rig.clear()
