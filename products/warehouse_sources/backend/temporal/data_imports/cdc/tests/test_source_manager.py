import contextlib

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN, CDC_SEQ_PROVENANCE
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import build_buffer_file_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
    CDCSourceManager,
    is_buffered_consolidated,
    serves_buffered_lane,
)

_TEAM_ID = 7
_SCHEMA_ID = "3f7c1f4e-0000-0000-0000-000000000001"
_PREFIX = f"bucket/cdc_producer/{_TEAM_ID}/{_SCHEMA_ID}"


def _table(ids: list[int], seqs: list[int]) -> pa.Table:
    return pa.table({"id": pa.array(ids, pa.int64())}).append_column(
        pa.field(CDC_SEQ_COLUMN, pa.int64(), metadata=CDC_SEQ_PROVENANCE), pa.array(seqs, pa.int64())
    )


def _parquet_bytes(table: pa.Table) -> bytes:
    buf = pa.BufferOutputStream()
    pq.write_table(table, buf)
    return buf.getvalue().to_pybytes()


def _key(start: int, end: int, index: int = 0) -> str:
    return f"{_PREFIX}/{build_buffer_file_name(start, end, index)}"


class _FakeS3:
    """Minimal stand-in for the async fsspec client the manager uses."""

    def __init__(self, files: dict[str, bytes], missing_prefix: bool = False) -> None:
        self.files = dict(files)
        self.removed: list[str] = []
        self.opened: list[str] = []
        self.missing_prefix = missing_prefix

    async def _ls(self, prefix, detail=True):
        if self.missing_prefix:
            raise FileNotFoundError(prefix)
        return [{"type": "file", "Key": key} for key in self.files]

    async def _rm(self, key):
        self.removed.append(key)
        self.files.pop(key, None)

    async def open_async(self, key, mode):
        self.opened.append(key)
        if key not in self.files:
            raise FileNotFoundError(key)
        data = self.files[key]

        @contextlib.asynccontextmanager
        async def _reader():
            handle = AsyncMock()
            handle.read = AsyncMock(return_value=data)
            yield handle

        return _reader()


@contextlib.contextmanager
def _patched(s3: _FakeS3, load_position: int | None):
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.aget_s3_client"
        ) as mock_client,
        patch.object(CDCSourceManager, "_read_load_position", AsyncMock(return_value=load_position)),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.get_buffer_prefix",
            return_value=f"s3://{_PREFIX}",
        ),
    ):
        mock_client.return_value.__aenter__ = AsyncMock(return_value=s3)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        yield


def _manager() -> CDCSourceManager:
    inputs = MagicMock()
    inputs.team_id = _TEAM_ID
    inputs.schema_id = _SCHEMA_ID
    inputs.reset_pipeline = False
    return CDCSourceManager(inputs=inputs, logger=AsyncMock())


async def _collect(s3: _FakeS3, load_position: int | None = None, **kwargs) -> list[pa.Table]:
    with _patched(s3, load_position):
        return [t async for t in _manager().get_items("users", **kwargs)]


def _schema(**overrides) -> MagicMock:
    schema = MagicMock()
    schema.is_cdc = overrides.get("is_cdc", True)
    schema.cdc_mode = overrides.get("cdc_mode", "streaming")
    schema.cdc_table_mode = overrides.get("cdc_table_mode", "consolidated")
    schema.initial_sync_complete = overrides.get("initial_sync_complete", True)
    return schema


@pytest.mark.asyncio
class TestCDCSourceManager:
    async def test_files_are_read_in_position_order_not_listing_order(self):
        # S3 returns keys in arbitrary order; only the filename's position range may order them.
        s3 = _FakeS3(
            {
                _key(300, 399): _parquet_bytes(_table([3], [300])),
                _key(100, 199): _parquet_bytes(_table([1], [100])),
                _key(200, 299): _parquet_bytes(_table([2], [200])),
            }
        )

        tables = await _collect(s3)

        assert len(tables) == 1
        assert tables[0].column(CDC_SEQ_COLUMN).to_pylist() == [100, 200, 300]

    async def test_files_sharing_a_position_range_order_by_file_index(self):
        # One transaction's events share a commit position, so the index is the only tiebreak.
        s3 = _FakeS3(
            {
                _key(100, 100, 2): _parquet_bytes(_table([3], [100])),
                _key(100, 100, 0): _parquet_bytes(_table([1], [100])),
                _key(100, 100, 1): _parquet_bytes(_table([2], [100])),
            }
        )

        tables = await _collect(s3)

        assert tables[0].column("id").to_pylist() == [1, 2, 3]

    async def test_fully_applied_files_are_deleted_and_never_read(self):
        s3 = _FakeS3(
            {
                _key(100, 199): _parquet_bytes(_table([1], [100])),
                _key(200, 299): _parquet_bytes(_table([2], [200])),
            }
        )

        tables = await _collect(s3, load_position=250)

        assert s3.removed == [_key(100, 199)]
        assert s3.opened == [_key(200, 299)]
        assert tables[0].column("id").to_pylist() == [2]

    async def test_a_file_ending_at_the_position_is_still_read(self):
        # Equality is not proof of application: one transaction shares a commit position across
        # files, so a file ending exactly at the watermark can still hold unapplied rows.
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1], [200]))})

        tables = await _collect(s3, load_position=200)

        assert s3.removed == []
        assert len(tables) == 1

    async def test_no_files_are_deleted_before_anything_is_committed(self):
        s3 = _FakeS3({_key(100, 199): _parquet_bytes(_table([1], [100]))})

        await _collect(s3, load_position=None)

        assert s3.removed == []

    async def test_files_are_not_deleted_on_yield(self):
        # The v3 batcher buffers across yields, so a yielded table can still be in memory. Only a
        # committed position may delete a file.
        s3 = _FakeS3(
            {
                _key(100, 199): _parquet_bytes(_table(list(range(6000)), [100] * 6000)),
                _key(200, 299): _parquet_bytes(_table([1], [200])),
            }
        )

        tables = await _collect(s3)

        assert len(tables) == 2
        assert s3.removed == []

    async def test_names_that_do_not_match_the_contract_are_ignored(self):
        s3 = _FakeS3(
            {
                f"{_PREFIX}/_delta_log": b"",
                f"{_PREFIX}/whatever.parquet": b"",
                _key(100, 199): _parquet_bytes(_table([1], [100])),
            }
        )

        tables = await _collect(s3)

        assert s3.opened == [_key(100, 199)]
        assert len(tables) == 1

    async def test_a_file_consumed_between_listing_and_read_is_skipped(self):
        s3 = _FakeS3({_key(100, 199): _parquet_bytes(_table([1], [100]))})
        s3.files.pop(_key(100, 199))  # a concurrent run deleted it after our listing

        tables = await _collect(s3)

        assert tables == []

    async def test_a_missing_prefix_yields_nothing(self):
        # Before capture's first write the prefix does not exist; that is a no-op, not a failure.
        assert await _collect(_FakeS3({}, missing_prefix=True)) == []

    async def test_batches_are_cut_at_the_row_limit(self):
        s3 = _FakeS3(
            {
                _key(i * 100, i * 100 + 99): _parquet_bytes(_table(list(range(400)), [i * 100] * 400))
                for i in range(1, 4)
            }
        )

        tables = await _collect(s3, batch_row_limit=500)

        # 400 → under the limit, 800 → cut, then the trailing 400 flushes at the end.
        assert [t.num_rows for t in tables] == [800, 400]


class TestBufferedGating:
    @parameterized.expand(
        [
            ("not_cdc", {"is_cdc": False}),
            ("still_snapshotting", {"cdc_mode": "snapshot"}),
            ("companion_lane", {"cdc_table_mode": "cdc_only"}),
            ("both_lanes", {"cdc_table_mode": "both"}),
            ("no_table_yet", {"initial_sync_complete": False}),
        ]
    )
    def test_ineligible_schemas_stay_on_the_legacy_path(self, _name, overrides):
        assert serves_buffered_lane(_schema(**overrides)) is False

    def test_a_consolidated_streaming_schema_serves_the_buffered_lane(self):
        assert serves_buffered_lane(_schema()) is True

    @parameterized.expand([("legacy",), ("",), ("nonsense",)])
    def test_a_source_that_was_not_flipped_stays_on_the_legacy_path(self, ingest_mode):
        assert is_buffered_consolidated(_schema(), ingest_mode=ingest_mode, reset_pipeline=False) is False

    def test_a_reset_stands_down_so_the_snapshot_can_rebuild(self):
        assert is_buffered_consolidated(_schema(), ingest_mode="buffered", reset_pipeline=True) is False

    def test_a_flipped_consolidated_schema_consumes_the_buffer(self):
        assert is_buffered_consolidated(_schema(), ingest_mode="buffered", reset_pipeline=False) is True
