"""Fixtures for testing itch-py against a real `itch-sim`.

Until `itch` publishes releases, the sim and the conformance vectors come from a local `itch`
checkout:

- `ITCH_SIM`: path to an `itch-sim` binary.
- `ITCH_VECTORS`: path to `vectors-v1.json`.
- Otherwise, `ITCH_REPO` or the first sibling `itch-integration` or `itch` checkout: the sim is
  built there with `cargo build -p itch-sim` and the vectors are read from `docs/protocol/`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ITCH_PY = Path(__file__).resolve().parent.parent
READY = "itch-sim listening on "


def _itch_repo() -> Path:
    if repo := os.environ.get("ITCH_REPO"):
        return Path(repo)
    for sibling in ("itch-integration", "itch"):
        repo = ITCH_PY.parent / sibling
        if (repo / "crates" / "itch-sim").is_dir():
            return repo
    pytest.fail(
        "No itch checkout found. Set ITCH_SIM and ITCH_VECTORS, or ITCH_REPO to an itch checkout."
    )


def _sim_binary() -> Path:
    if sim := os.environ.get("ITCH_SIM"):
        return Path(sim)
    repo = _itch_repo()
    subprocess.run(["cargo", "build", "--quiet", "-p", "itch-sim"], cwd=repo, check=True)
    return repo / "target" / "debug" / ("itch-sim.exe" if sys.platform == "win32" else "itch-sim")


@pytest.fixture(scope="session")
def vectors() -> dict[str, Any]:
    """The parsed conformance vectors."""
    path = os.environ.get("ITCH_VECTORS") or _itch_repo() / "docs" / "protocol" / "vectors-v1.json"
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sim() -> Iterator[str]:
    """One `itch-sim` for the whole session. Yields its `tcp://host:port` name."""
    process = subprocess.Popen([_sim_binary()], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout is not None
        line = process.stdout.readline().strip()
        if not line.startswith(READY):
            pytest.fail(f"itch-sim didn't start: {line!r}")
        yield line.removeprefix(READY)
    finally:
        process.kill()
        process.wait()
        if process.stdout:
            process.stdout.close()
