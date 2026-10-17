"""Fixtures for testing itch-py against a real `itch-sim`.

The sim and the conformance vectors come from the first of:

- `ITCH_SIM`: path to an `itch-sim` binary, and `ITCH_VECTORS`: path to `vectors-v1.json`.
- `ITCH_REPO` or the first sibling `itch-integration` or `itch` checkout: the sim is built there
  with `cargo build -p itch-sim` and the vectors are read from `docs/protocol/`.
- The `itch` release pinned in `itch_release.py`, downloaded once into a local cache.
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from itch_release import TAG, Release, fetch

from itch import Rig

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


@functools.cache
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


class RunningSim:
    """An `itch-sim` process, stopped on exit."""

    def __init__(self, *args: str) -> None:
        self._process = subprocess.Popen([_sim_binary(), *args], stdout=subprocess.PIPE, text=True)
        assert self._process.stdout is not None
        line = self._process.stdout.readline().strip()
        if not line.startswith(READY):
            self.stop()
            pytest.fail(f"itch-sim didn't start: {line!r}")
        self.url = line.removeprefix(READY)
        """Its `tcp://host:port` name."""

    def stop(self) -> None:
        """Kills the sim, as unplugging a Rig would end its connections."""
        self._process.kill()
        self._process.wait()
        if self._process.stdout:
            self._process.stdout.close()

    def __enter__(self) -> RunningSim:
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


@pytest.fixture(scope="session")
def sim() -> Iterator[str]:
    """One `itch-sim` for the whole session. Yields its `tcp://host:port` name."""
    with RunningSim() as running:
        yield running.url


@pytest.fixture
def own_sim() -> Iterator[RunningSim]:
    """An `itch-sim` of the test's own, which it may stop."""
    with RunningSim() as running:
        yield running


@pytest.fixture
def rig(sim: str) -> Iterator[Rig]:
    """A connection to the session's `itch-sim`."""
    with Rig.connect(sim) as rig:
        yield rig
