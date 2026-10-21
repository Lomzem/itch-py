"""The Profile template in `docs/` loads and drives a Rig as the guide says."""

from profile_template import AcmeWidget as Template

from itch import Rig


def test_the_template_drives_a_rig(rig: Rig) -> None:
    dut = Template(rig)
    rig.clear_all()
    with dut.batch():
        dut.resolution.set("1080p")
        dut.mode.set("night", encoding=2)
    assert str(dut) == (
        'AcmeWidget(resolution="1080p", standby="disabled", picture="black", tone="silent", '
        'refresh="50hz", mode="night" (Encoding 2))'
    )
