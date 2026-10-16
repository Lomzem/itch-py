"""Fixtures for testing itch-py against a real `itch-sim`.

The sim and the conformance vectors come from the first of:

- `ITCH_SIM`: path to an `itch-sim` binary, and `ITCH_VECTORS`: path to `vectors-v1.json`.
- `ITCH_REPO` or the first sibling `itch-integration` or `itch` checkout: the sim is built there
  with `cargo build -p itch-sim` and the vectors are read from `docs/protocol/`.
- The `itch` release pinned in `itch_release.py`, downloaded once into a local cache.
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
from itch_release import TAG, Release, fetch

ITCH_PY = Path(__file__).resolve().parent.parent
READY = "itch-sim listening on "


def _itch_repo() -> Path | None:
    if repo := os.environ.get("ITCH_REPO"):
        return Path(repo)
    for sibling in ("itch-integration", "itch"):
        repo = ITCH_PY.parent / sibling
        if (repo / "crates" / "itch-sim").is_dir():
            return repo
    return None


def _release() -> Release:
    try:
        return fetch()
    except RuntimeError as err:
        problem = str(err)
    pytest.fail(
        f"{problem}\nCan't get itch {TAG}. Set ITCH_SIM and ITCH_VECTORS, or ITCH_REPO.",
        pytrace=False,
    )


def _sim_binary() -> Path:
    if sim := os.environ.get("ITCH_SIM"):
        return Path(sim)
    repo = _itch_repo()
    if repo is None:
        return _release().sim
    subprocess.run(["cargo", "build", "--quiet", "-p", "itch-sim"], cwd=repo, check=True)
    return repo / "target" / "debug" / ("itch-sim.exe" if sys.platform == "win32" else "itch-sim")


@pytest.fixture(scope="session")
def vectors() -> dict[str, Any]:
    """The parsed conformance vectors."""
    if env := os.environ.get("ITCH_VECTORS"):
        path = Path(env)
    elif repo := _itch_repo():
        path = repo / "docs" / "protocol" / "vectors-v1.json"
    else:
        path = _release().vectors
    return json.loads(path.read_text(encoding="utf-8"))


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
