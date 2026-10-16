"""The one `itch` release whose `itch-sim` and vectors the tests run against.

Moving to a new protocol means bumping `TAG`. `fetch` downloads the release's sim and vectors into
a local cache, checks them against the release manifest's hashes and works offline once cached.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

TAG = "v0.1.0"
BASE_URL = "https://github.com/Lomzem/itch/releases/download"
SIM_ASSET = "itch-sim-windows-x86_64.exe" if sys.platform == "win32" else "itch-sim-linux-x86_64"
VECTORS_ASSET = "vectors-v1.json"


@dataclass(frozen=True)
class Release:
    sim: Path
    vectors: Path


def fetch(tag: str = TAG, *, base_url: str = BASE_URL, cache: Path | None = None) -> Release:
    """Returns the cached sim and vectors of `tag`, downloading them first if needed."""
    directory = (cache or default_cache()) / tag
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "manifest.json"
    if not manifest.exists():
        _download(f"{base_url}/{tag}/manifest.json", manifest)
    hashes: dict[str, str] = json.loads(manifest.read_text(encoding="utf-8"))["sha256"]

    def asset(name: str) -> Path:
        path = directory / name
        if path.exists() and _sha256(path) == hashes[name]:
            return path
        _download(f"{base_url}/{tag}/{name}", path)
        if _sha256(path) != hashes[name]:
            path.unlink()
            raise RuntimeError(f"{name} from itch {tag} doesn't match its manifest hash")
        return path

    sim = asset(SIM_ASSET)
    sim.chmod(sim.stat().st_mode | 0o111)
    return Release(sim=sim, vectors=asset(VECTORS_ASSET))


def default_cache() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "itch-py"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "itch-py"


def _download(url: str, path: Path) -> None:
    """Writes `url` to `path`, which never holds a partial download."""
    part = path.with_name(f"{path.name}.part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            part.write_bytes(response.read())
    except OSError as err:
        raise RuntimeError(f"Couldn't download {url}: {err}") from err
    part.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
