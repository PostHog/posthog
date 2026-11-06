from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

import pytest

from hogli_commands.disk_usage import measure_disk_usage

_FILE_BYTES = 256 * 1024


def _write_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(_FILE_BYTES))
    return path


def _clone(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-c", str(source), str(destination)], check=True)


@pytest.mark.parametrize(
    ("layout", "expected_freeable_files", "expected_allocated_files"),
    [
        ("own_file", 1, 1),
        ("hardlink_from_outside", 0, 1),
        ("both_hardlinks_inside", 1, 1),
        ("symlink_to_outside", 0, 0),
        pytest.param(
            "apfs_clone_from_outside",
            0,
            1,
            marks=pytest.mark.skipif(sys.platform != "darwin", reason="APFS clones need macOS"),
        ),
    ],
)
def test_counts_as_freeable_only_blocks_no_file_outside_the_paths_shares(
    tmp_path, layout: str, expected_freeable_files: int, expected_allocated_files: int
) -> None:
    store = _write_file(tmp_path / "store" / "package.js")
    deps = tmp_path / "wt" / "node_modules"
    deps.mkdir(parents=True)
    if layout == "own_file":
        _write_file(deps / "package.js")
    elif layout == "hardlink_from_outside":
        os.link(store, deps / "package.js")
    elif layout == "both_hardlinks_inside":
        _write_file(deps / "a.js")
        os.link(deps / "a.js", deps / "b.js")
    elif layout == "symlink_to_outside":
        (deps / "package.js").symlink_to(store)
    else:
        _clone(store, deps / "package.js")

    usage = measure_disk_usage([deps])

    assert usage.freeable_bytes == pytest.approx(expected_freeable_files * _FILE_BYTES, rel=0.1)
    assert usage.allocated_bytes == pytest.approx(expected_allocated_files * _FILE_BYTES, rel=0.1)
