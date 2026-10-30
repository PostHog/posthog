import threading
from pathlib import Path

import pytest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import row_group_sizes
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.row_group_sizes import (
    RowGroupSizeReader,
    _FooterCache,
    _ReadSlots,
)


def _write(path: Path, rows: int, row_group_rows: int) -> int:
    table = pa.table({"id": pa.array(range(rows), pa.int64()), "v": [f"value-{i:06d}" * 4 for i in range(rows)]})
    pq.write_table(table, path, row_group_size=row_group_rows, compression="none")
    return path.stat().st_size


def _expected(path: str) -> int:
    metadata = pq.read_metadata(path)
    return max(
        sum(metadata.row_group(i).column(c).total_compressed_size for c in range(metadata.num_columns))
        for i in range(metadata.num_row_groups)
    )


_READ_METADATA = pq.read_metadata


class _Footers:
    """Counts footer reads, and fails or stalls the reads of chosen files."""

    def __init__(self, broken: frozenset[str] = frozenset(), stalled: frozenset[str] = frozenset()) -> None:
        self.read: list[str] = []
        self._broken = broken
        self._stalled = stalled
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, path: str, filesystem: pafs.FileSystem) -> pq.FileMetaData:
        with self._lock:
            self.read.append(path)
        if path in self._broken:
            raise OSError("unreachable")
        if path in self._stalled:
            self.release.wait(5)
        return _READ_METADATA(path, filesystem=filesystem)


@pytest.fixture
def files(tmp_path: Path) -> dict[str, int]:
    # Many small row groups, one row group, and a small file.
    return {
        str(tmp_path / name): _write(tmp_path / name, rows, row_group_rows)
        for name, rows, row_group_rows in (("many", 4000, 500), ("one", 3000, 3000), ("small", 100, 100))
    }


def _read(sizes: dict[str, int], footers: _Footers, cache: _FooterCache | None = None, **kwargs):
    reader = RowGroupSizeReader(
        "table", open_filesystem=lambda _sizes: pafs.LocalFileSystem(), cache=cache or _FooterCache(100), **kwargs
    )
    with patch.object(row_group_sizes.pq, "read_metadata", side_effect=footers):
        return reader.largest_row_groups(sizes)


class TestRowGroupSizeReader:
    def test_reads_the_largest_row_group_of_each_file(self, files: dict[str, int]) -> None:
        result = _read(files, _Footers())

        assert result.bytes_by_path == {path: _expected(path) for path in files}
        assert result.footers_read == 3
        many, one = (next(p for p in files if p.endswith(name)) for name in ("many", "one"))
        assert result.bytes_by_path[many] < files[many] / 4
        assert result.bytes_by_path[one] > files[one] / 2

    def test_a_cached_footer_is_not_read_again(self, files: dict[str, int]) -> None:
        cache = _FooterCache(100)
        footers = _Footers()
        first = _read(files, footers, cache)
        second = _read(files, footers, cache)

        assert second.bytes_by_path == first.bytes_by_path
        assert (second.footers_read, len(footers.read)) == (0, 3)

    def test_the_read_cap_keeps_the_largest_files(self, files: dict[str, int]) -> None:
        footers = _Footers()
        result = _read(files, footers, max_reads=2)

        largest_two = sorted(sorted(files, key=files.__getitem__, reverse=True)[:2])
        assert sorted(result.bytes_by_path) == largest_two
        assert sorted(footers.read) == largest_two

    @pytest.mark.parametrize("failure", ["broken", "stalled"])
    def test_a_file_that_cannot_be_read_is_left_out(self, failure: str, files: dict[str, int]) -> None:
        bad = next(p for p in files if p.endswith("many"))
        footers = _Footers(**{failure: frozenset({bad})})
        try:
            result = _read(files, footers, timeout_s=0.5)
        finally:
            footers.release.set()

        assert set(result.bytes_by_path) == set(files) - {bad}
        assert result.footers_read == 2

    def test_no_files_reads_nothing(self) -> None:
        footers = _Footers()
        assert _read({}, footers).bytes_by_path == {}
        assert footers.read == []

    def test_reads_a_uri_encoded_path_by_its_decoded_name(self, tmp_path: Path) -> None:
        (tmp_path / "p=a b").mkdir()
        size = _write(tmp_path / "p=a b" / "file.parquet", 2000, 500)
        encoded = str(tmp_path / "p=a%20b" / "file.parquet")

        result = _read({encoded: size}, _Footers())

        assert result.bytes_by_path == {encoded: _expected(str(tmp_path / "p=a b" / "file.parquet"))}

    def test_stalled_reads_hold_their_slots_so_later_calls_read_nothing(self, files: dict[str, int]) -> None:
        many = next(p for p in files if p.endswith("many"))
        slots = _ReadSlots(1)
        footers = _Footers(stalled=frozenset({many}))
        try:
            stalled = _read(files, footers, slots=slots, timeout_s=0.2)
            later = _read(files, footers, slots=slots)
        finally:
            footers.release.set()

        assert (stalled.bytes_by_path, later.bytes_by_path) == ({}, {})
        assert footers.read == [many]

    def test_a_filesystem_that_cannot_open_frees_its_slots(self, files: dict[str, int]) -> None:
        slots = _ReadSlots(len(files))

        def broken(_sizes: object) -> pafs.FileSystem:
            raise OSError("no credentials")

        reader = RowGroupSizeReader("table", open_filesystem=broken, cache=_FooterCache(100), slots=slots)
        with pytest.raises(OSError):
            reader.largest_row_groups(files)

        assert slots.acquire(len(files)) == len(files)
