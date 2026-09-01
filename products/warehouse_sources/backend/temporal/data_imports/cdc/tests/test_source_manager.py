import datetime as dt
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
    has_pending_legacy_backlog,
    is_buffered_consolidated,
    scheduled_sync_consumes_buffer,
    serves_buffered_lane,
)

_TEAM_ID = 7
_SCHEMA_ID = "3f7c1f4e-0000-0000-0000-000000000001"
_PREFIX = f"bucket/cdc_producer/{_TEAM_ID}/{_SCHEMA_ID}"

_NOW = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.UTC)
# Older than any completed-run start minus the clock-skew margin.
_OLD_MTIME = _NOW - dt.timedelta(hours=2)


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

    def __init__(
        self,
        files: dict[str, bytes],
        missing_prefix: bool = False,
        mtimes: dict[str, dt.datetime] | None = None,
    ) -> None:
        self.files = dict(files)
        self.removed: list[str] = []
        self.opened: list[str] = []
        self.missing_prefix = missing_prefix
        self.mtimes = mtimes or {}

    async def _ls(self, prefix, detail=True, refresh=False):
        # The manager must always bypass the fsspec dircache — capture writes through a different
        # process, so a cached listing could miss its files indefinitely.
        assert refresh, "buffer listings must pass refresh=True"
        if self.missing_prefix:
            raise FileNotFoundError(prefix)
        return [{"type": "file", "Key": key, "LastModified": self.mtimes.get(key, _OLD_MTIME)} for key in self.files]

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
def _patched(s3: _FakeS3, load_position: int | None, proof_time: dt.datetime | None):
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.aget_s3_client"
        ) as mock_client,
        patch.object(CDCSourceManager, "_read_consume_state", AsyncMock(return_value=(load_position, None))),
        patch.object(CDCSourceManager, "_completed_listing_time", AsyncMock(return_value=proof_time)),
        patch.object(CDCSourceManager, "_stamp_listing", AsyncMock()) as mock_stamp,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.get_buffer_prefix",
            return_value=f"s3://{_PREFIX}",
        ),
    ):
        mock_client.return_value.__aenter__ = AsyncMock(return_value=s3)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        yield mock_stamp


def _manager() -> CDCSourceManager:
    inputs = MagicMock()
    inputs.team_id = _TEAM_ID
    inputs.schema_id = _SCHEMA_ID
    inputs.reset_pipeline = False
    return CDCSourceManager(inputs=inputs, logger=AsyncMock())


async def _collect(
    s3: _FakeS3,
    load_position: int | None = None,
    proof_time: dt.datetime | None = None,
    **kwargs,
) -> list[pa.Table]:
    with _patched(s3, load_position, proof_time):
        return [t async for t in _manager().get_items("users", **kwargs)]


def _schema(**overrides) -> MagicMock:
    schema = MagicMock()
    schema.is_cdc = overrides.get("is_cdc", True)
    schema.cdc_mode = overrides.get("cdc_mode", "streaming")
    schema.cdc_table_mode = overrides.get("cdc_table_mode", "consolidated")
    schema.initial_sync_complete = overrides.get("initial_sync_complete", True)
    schema.sync_type_config = overrides.get("sync_type_config", {})
    schema.source.job_inputs = overrides.get("job_inputs", {})
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

    async def test_files_strictly_below_the_position_are_deleted_and_never_read(self):
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

    async def test_a_trailing_file_is_deleted_once_a_completed_listing_predates_it(self):
        # Position alone cannot prove the file at the floor consumed, so an idle schema would
        # otherwise re-merge and re-bill its trailing file on every sync forever.
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1], [200]))})

        tables = await _collect(s3, load_position=200, proof_time=_OLD_MTIME + dt.timedelta(hours=1))

        assert s3.removed == [_key(100, 200)]
        assert tables == []

    @parameterized.expand(
        [
            # A file written after the proving run's listing was never in it — it can hold the
            # unread tail of a transaction split across files (all rows share one position).
            ("written_after_the_proving_listing", _NOW, _NOW - dt.timedelta(minutes=30)),
            # Within the clock-skew margin of the listing, existence in it is unproven.
            ("within_the_skew_margin", _NOW - dt.timedelta(minutes=32), _NOW - dt.timedelta(minutes=30)),
            ("no_completed_listing_yet", _OLD_MTIME, None),
        ]
    )
    async def test_a_file_at_the_position_is_kept_when_consumption_is_unproven(self, _name, mtime, proof_time):
        key = _key(100, 200)
        s3 = _FakeS3({key: _parquet_bytes(_table([1], [200]))}, mtimes={key: mtime})

        tables = await _collect(s3, load_position=200, proof_time=proof_time)

        assert s3.removed == []
        assert len(tables) == 1

    async def test_no_files_are_deleted_before_anything_is_committed(self):
        s3 = _FakeS3({_key(100, 199): _parquet_bytes(_table([1], [100]))})

        await _collect(s3, load_position=None, proof_time=_NOW)

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
        assert is_buffered_consolidated(_schema(), ingest_mode=ingest_mode) is False

    def test_a_flipped_consolidated_schema_consumes_the_buffer(self):
        assert is_buffered_consolidated(_schema(), ingest_mode="buffered") is True

    def test_a_flipped_schema_forces_the_buffered_consumer_on_its_scheduled_sync(self):
        assert scheduled_sync_consumes_buffer(_schema(job_inputs={"cdc_ingest_mode": "buffered"})) is True

    @parameterized.expand(
        [
            ("source_never_flipped", {}),
            ("no_job_inputs", {"job_inputs": None}),
            ("companion_lane", {"job_inputs": {"cdc_ingest_mode": "buffered"}, "cdc_table_mode": "cdc_only"}),
            ("still_snapshotting", {"job_inputs": {"cdc_ingest_mode": "buffered"}, "cdc_mode": "snapshot"}),
        ]
    )
    def test_the_scheduled_sync_is_not_forced_off_the_flag_for(self, _name, overrides):
        assert scheduled_sync_consumes_buffer(_schema(**overrides)) is False


class TestPendingLegacyBacklog:
    # Legacy deliveries carry no position column, so a consumer merge racing them can be overwritten
    # by an older row. These prove both backlog forms hold the consumer off.

    def test_deferred_runs_are_a_backlog_without_touching_the_queue(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.psycopg"
        ) as mock_psycopg:
            assert has_pending_legacy_backlog(_schema(sync_type_config={"cdc_deferred_runs": [{"x": 1}]})) is True
            mock_psycopg.Connection.connect.assert_not_called()

    @parameterized.expand([("batches_pending", 12.5, True), ("queue_drained", None, False)])
    def test_sourcebatch_state_decides_when_no_deferred_runs(self, _name, age, expected):
        schema = _schema()
        schema.team_id = _TEAM_ID
        schema.id = _SCHEMA_ID
        with (
            patch("products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.psycopg"),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.BatchQueue.get_oldest_non_terminal_batch_age_seconds",
                return_value=age,
            ),
        ):
            assert has_pending_legacy_backlog(schema) is expected


@pytest.mark.asyncio
class TestListingProof:
    # The deletion proof must come only from a run that listed the buffer AND completed. A gated
    # no-op run (which never lists) or a crashed run (whose job never completes) must prove nothing.

    async def test_every_consuming_run_stamps_its_listing(self):
        s3 = _FakeS3({_key(100, 199): _parquet_bytes(_table([1], [100]))})

        with _patched(s3, None, None) as mock_stamp:
            [t async for t in _manager().get_items("users")]

        mock_stamp.assert_awaited_once()

    @parameterized.expand([("job_completed", True, True), ("job_not_completed", False, False)])
    async def test_a_stamp_proves_only_once_its_job_completes(self, _name, completed, expect_proof):
        listing = {"listed_at": _NOW.isoformat(), "job_id": "018f0000-0000-0000-0000-000000000001"}
        exists_qs = MagicMock()
        exists_qs.exists.return_value = completed

        with patch(
            "products.warehouse_sources.backend.models.external_data_job.ExternalDataJob.objects.filter",
            return_value=exists_qs,
        ):
            proof = await _manager()._completed_listing_time(listing)

        assert (proof == _NOW) is expect_proof
        assert (proof is None) is (not expect_proof)

    @parameterized.expand(
        [
            ("no_stamp", None),
            ("malformed_date", {"listed_at": "not-a-date", "job_id": "018f0000-0000-0000-0000-000000000001"}),
            ("naive_timestamp", {"listed_at": "2026-08-14T12:00:00", "job_id": "018f0000-0000-0000-0000-000000000001"}),
            ("malformed_job_id", {"listed_at": "2026-08-14T12:00:00+00:00", "job_id": "not-a-uuid"}),
            ("missing_job", {"listed_at": "2026-08-14T12:00:00+00:00"}),
        ]
    )
    async def test_unusable_stamps_prove_nothing(self, _name, listing):
        assert await _manager()._completed_listing_time(listing) is None
