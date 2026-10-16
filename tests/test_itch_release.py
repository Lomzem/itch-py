"""Downloading the pinned `itch` release, served here from a local HTTP server."""

import hashlib
import json
import os
import sys
import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from itch_release import SIM_ASSET, fetch

SIM = b"#!/bin/sh\necho fake itch-sim\n"
VECTORS = b'{"format": 1, "protocol": 1}\n'


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def publish(directory: Path, assets: dict[str, bytes], hashes: dict[str, bytes]) -> None:
    """Writes a release's assets and a manifest hashing `hashes`."""
    directory.mkdir()
    for name, content in assets.items():
        (directory / name).write_bytes(content)
    manifest = {
        "tag": "v9.9.9",
        "commit": "0" * 40,
        "protocol": 1,
        "sha256": {name: hashlib.sha256(content).hexdigest() for name, content in hashes.items()},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """Serves `tmp_path/releases` and yields its URL and directory."""
    root = tmp_path / "releases"
    root.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=root))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", root
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_fetch_downloads_the_release_and_then_runs_offline(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    url, root = server
    assets = {SIM_ASSET: SIM, "vectors-v1.json": VECTORS}
    publish(root / "v9.9.9", assets, assets)
    cache = tmp_path / "cache"

    release = fetch("v9.9.9", base_url=url, cache=cache)
    assert release.sim.read_bytes() == SIM
    assert release.vectors.read_bytes() == VECTORS
    if sys.platform != "win32":
        assert os.access(release.sim, os.X_OK)

    (root / "v9.9.9" / SIM_ASSET).unlink()
    (root / "v9.9.9" / "manifest.json").unlink()
    offline = fetch("v9.9.9", base_url=url, cache=cache)
    assert offline.sim.read_bytes() == SIM
    assert offline.vectors.read_bytes() == VECTORS


def test_fetch_refuses_an_asset_that_does_not_match_the_manifest(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    url, root = server
    publish(
        root / "v9.9.9",
        {SIM_ASSET: b"tampered", "vectors-v1.json": VECTORS},
        {SIM_ASSET: SIM, "vectors-v1.json": VECTORS},
    )

    with pytest.raises(RuntimeError, match=SIM_ASSET):
        fetch("v9.9.9", base_url=url, cache=tmp_path / "cache")
