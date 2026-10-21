"""The Profile template in `docs/` loads and drives a Rig as the guide says."""

from profile_template import AcmeWidget as Template

from itch import Rig


def test_the_template_drives_a_rig(sim: str) -> None:
    with Rig.connect(sim, Template) as dut:
        dut.clear_all()
        dut.apply(resolution="1080p", mode=("night", 2))
        assert str(dut) == (
            'AcmeWidget(resolution="1080p", standby="disabled", picture="black", tone="silent", '
            'refresh="50hz", mode="night" (Encoding 2))'
        )
