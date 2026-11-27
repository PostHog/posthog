from __future__ import annotations

import os
import sys
import struct
import subprocess
from pathlib import Path

import pytest

from hogli_commands import disk_usage
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
        ("own_file_in_subfolder", 1, 1),
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
    elif layout == "own_file_in_subfolder":
        _write_file(deps / "package" / "dist" / "index.js")
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


def test_counts_every_file_in_a_folder_that_takes_more_than_one_bulk_read(tmp_path) -> None:
    deps = tmp_path / "node_modules"
    deps.mkdir()
    file_count = 2000
    for index in range(file_count):
        (deps / f"chunk-{index}.js").write_bytes(os.urandom(4096))

    usage = measure_disk_usage([deps])

    assert usage.allocated_bytes == pytest.approx(file_count * 4096, rel=0.1)


def _bulk_entry(name: str, *, error: int, with_file_attributes: bool) -> bytes:
    common = disk_usage._ATTR_CMN_RETURNED_ATTRS | disk_usage._ATTR_CMN_NAME | disk_usage._ATTR_CMN_ERROR
    file_attributes = extended = 0
    attributes_after_name = b""
    if with_file_attributes:
        common |= disk_usage._ATTR_CMN_OBJTYPE | disk_usage._ATTR_CMN_FILEID
        file_attributes = disk_usage._ATTR_FILE_LINKCOUNT | disk_usage._ATTR_FILE_ALLOCSIZE
        extended = disk_usage._ATTR_CMNEXT_PRIVATESIZE
        attributes_after_name = struct.pack("<IQIqq", disk_usage._VREG, 42, 1, 8192, 4096)
    name_bytes = name.encode() + b"\0"
    name_reference_at = disk_usage._BULK_ENTRY_HEADER.size + 4
    name_at = name_reference_at + disk_usage._ATTRIBUTE_REFERENCE.size + len(attributes_after_name)
    body = (
        struct.pack("<5I", common, 0, 0, file_attributes, extended)
        + struct.pack("<I", error)
        + struct.pack("<iI", name_at - name_reference_at, len(name_bytes))
        + attributes_after_name
        + name_bytes
    )
    return struct.pack("<I", 4 + len(body)) + body


@pytest.mark.parametrize("case", ["file_with_zero_error", "file_with_error", "folder_with_error"])
def test_parses_bulk_entries_in_the_layout_the_kernel_documents(tmp_path, case: str) -> None:
    (tmp_path / "package.js").write_bytes(os.urandom(4096))
    (tmp_path / "dist").mkdir()
    file_status = (tmp_path / "package.js").stat()
    if case == "file_with_zero_error":
        entry = _bulk_entry("package.js", error=0, with_file_attributes=True)
        expected: object = disk_usage._FileBlocks(inode=42, link_count=1, allocated_bytes=8192, unshared_bytes=4096)
    elif case == "file_with_error":
        entry = _bulk_entry("package.js", error=5, with_file_attributes=False)
        allocated = file_status.st_blocks * 512
        expected = disk_usage._FileBlocks(
            inode=file_status.st_ino, link_count=1, allocated_bytes=allocated, unshared_bytes=allocated
        )
    else:
        entry = _bulk_entry("dist", error=5, with_file_attributes=False)
        expected = str(tmp_path / "dist")

    parsed = disk_usage._parse_bulk_entry(entry, 0, str(tmp_path), tmp_path.stat().st_dev)

    assert parsed == expected
