"""The `RunningSim` test fixture's startup deadline."""

import sys
import time
from pathlib import Path

import pytest
from conftest import RunningSim


def test_a_sim_that_never_says_it_is_ready_fails_with_its_output(tmp_path: Path) -> None:
    stuck = tmp_path / "stuck_sim.py"
    stuck.write_text(
        "import sys, time\nsys.stdout.write('warming up')\nsys.stdout.flush()\ntime.sleep(60)\n"
    )
    started = time.monotonic()
    with pytest.raises(pytest.fail.Exception, match=r"within 0\.5 s.*'warming up'"):
        RunningSim(command=[sys.executable, str(stuck)], startup_timeout=0.5)
    assert time.monotonic() - started < 10
