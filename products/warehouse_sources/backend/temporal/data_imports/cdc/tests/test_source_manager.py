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
    COMPANION_WRITE_MODE,
    CONSOLIDATED_WRITE_MODE,
    CDCLane,
    CDCSourceManager,
    CDCWriteMode,
    _ConsumeState,
    companion_resource_name,
    consumes_buffer,
    has_batches_in_flight,
    scheduled_sync_consumes_buffer,
    select_lane,
    served_lanes,
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
def _patched(
    s3: _FakeS3,
    load_position: int | None,
    proof_time: dt.datetime | None,
    applied_position: int | None = None,
    applied_rows: int = 0,
    own_floor: int | None = None,
):
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.aget_s3_client"
        ) as mock_client,
        patch.object(
            CDCSourceManager,
            "_read_consume_state",
            AsyncMock(
                return_value=_ConsumeState(
                    floor=load_position,
                    own_floor=load_position if own_floor is None else own_floor,
                    stamps={},
                    applied_position=applied_position,
                    applied_rows=applied_rows,
                )
            ),
        ),
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
    applied_position: int | None = None,
    applied_rows: int = 0,
    own_floor: int | None = None,
    write_mode: CDCWriteMode = COMPANION_WRITE_MODE,
    **kwargs,
) -> list[pa.Table]:
    with _patched(s3, load_position, proof_time, applied_position, applied_rows, own_floor):
        return [t async for t in _manager().get_items("users", write_mode=write_mode, **kwargs)]


def _schema(**overrides) -> MagicMock:
    schema = MagicMock()
    schema.is_cdc = overrides.get("is_cdc", True)
    schema.cdc_mode = overrides.get("cdc_mode", "streaming")
    schema.cdc_table_mode = overrides.get("cdc_table_mode", "consolidated")
    schema.initial_sync_complete = overrides.get("initial_sync_complete", True)
    schema.sync_type_config = overrides.get("sync_type_config", {})
    schema.source.job_inputs = overrides.get("job_inputs", {})
    schema.name = overrides.get("name", "users")
    schema.resolved_s3_folder_name = overrides.get("resolved_s3_folder_name", "users")
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


class TestServedLanes:
    @parameterized.expand(
        [
            ("consolidated", "consolidated", [CDCLane(resource_name="users", write_mode="incremental_merge")]),
            ("cdc_only", "cdc_only", [CDCLane(resource_name="users_cdc", write_mode="scd2_append")]),
            (
                "both",
                "both",
                [
                    CDCLane(resource_name="users", write_mode="incremental_merge"),
                    CDCLane(resource_name="users_cdc", write_mode="scd2_append"),
                ],
            ),
        ]
    )
    def test_a_table_mode_names_the_tables_its_changes_feed(self, _name, table_mode, expected):
        assert served_lanes(_schema(cdc_table_mode=table_mode)) == expected

    def test_an_unrecognized_table_mode_feeds_nothing(self):
        # Fail closed: a mode this module cannot write must not reach the buffer at all.
        assert served_lanes(_schema(cdc_table_mode="something_new")) == []

    def test_the_companion_is_named_off_the_schema_not_the_folder(self):
        # The consolidated lane follows the snapshot's resolved folder, which diverges from `name`
        # for a row renamed bare to qualified. Following it here would append history into a table
        # no query reads — the companion is keyed on `name`, like its snapshot seed.
        schema = _schema(name="public.users", resolved_s3_folder_name="users")
        assert companion_resource_name(schema) == "public.users_cdc"


class TestLaneSelection:
    @parameterized.expand([("consolidated", "consolidated"), ("cdc_only", "cdc_only")])
    def test_a_single_lane_schema_always_serves_that_lane(self, _name, table_mode):
        schema = _schema(cdc_table_mode=table_mode)
        assert select_lane(schema) == served_lanes(schema)[0]

    def test_both_starts_on_the_consolidated_lane(self):
        assert select_lane(_schema(cdc_table_mode="both")).resource_name == "users"

    @parameterized.expand(
        [
            ("consolidated_ran_last", "users", "users_cdc"),
            ("companion_ran_last", "users_cdc", "users"),
        ]
    )
    def test_both_serves_the_lane_that_did_not_run_last(self, _name, last_served, expected):
        # One pipeline run writes one table, so the lanes take turns rather than racing.
        schema = _schema(
            cdc_table_mode="both",
            sync_type_config={"cdc_buffer_listing": {last_served: {"listed_at": _NOW.isoformat(), "job_id": "j"}}},
        )
        assert select_lane(schema).resource_name == expected

    def test_a_retry_of_the_same_job_serves_the_lane_that_job_already_stamped(self):
        # The failed attempt stamped its lane with this job id. Alternating off that stamp would
        # give both lanes the same job id, so completing the retry would prove a deletion for
        # files the first lane never committed.
        schema = _schema(
            cdc_table_mode="both",
            sync_type_config={"cdc_buffer_listing": {"users": {"listed_at": _NOW.isoformat(), "job_id": "job-1"}}},
        )

        assert select_lane(schema, job_id="job-1").resource_name == "users"
        assert select_lane(schema, job_id="job-2").resource_name == "users_cdc"

    def test_the_newest_stamp_decides_when_both_lanes_have_run(self):
        schema = _schema(
            cdc_table_mode="both",
            sync_type_config={
                "cdc_buffer_listing": {
                    "users": {"listed_at": (_NOW - dt.timedelta(minutes=5)).isoformat(), "job_id": "j1"},
                    "users_cdc": {"listed_at": _NOW.isoformat(), "job_id": "j2"},
                }
            },
        )
        assert select_lane(schema).resource_name == "users"


class TestBufferedGating:
    @parameterized.expand(
        [
            ("not_cdc", {"is_cdc": False}),
            ("still_snapshotting", {"cdc_mode": "snapshot"}),
            ("unrecognized_table_mode", {"cdc_table_mode": "something_new"}),
            ("no_table_yet", {"initial_sync_complete": False}),
        ]
    )
    def test_ineligible_schemas_stay_on_the_legacy_path(self, _name, overrides):
        assert serves_buffered_lane(_schema(**overrides)) is False

    @parameterized.expand([("consolidated",), ("cdc_only",), ("both",)])
    def test_every_streaming_table_mode_serves_the_buffered_lane(self, table_mode):
        assert serves_buffered_lane(_schema(cdc_table_mode=table_mode)) is True

    @parameterized.expand([("legacy",), ("",), ("nonsense",)])
    def test_a_source_that_was_not_flipped_stays_on_the_legacy_path(self, ingest_mode):
        assert consumes_buffer(_schema(), ingest_mode=ingest_mode) is False

    @parameterized.expand([("consolidated",), ("cdc_only",), ("both",)])
    def test_a_flipped_schema_consumes_the_buffer(self, table_mode):
        assert consumes_buffer(_schema(cdc_table_mode=table_mode), ingest_mode="buffered") is True

    @parameterized.expand([("consolidated",), ("cdc_only",), ("both",)])
    def test_a_flipped_schema_forces_the_buffered_consumer_on_its_scheduled_sync(self, table_mode):
        schema = _schema(job_inputs={"cdc_ingest_mode": "buffered"}, cdc_table_mode=table_mode)
        assert scheduled_sync_consumes_buffer(schema) is True

    @parameterized.expand(
        [
            ("source_never_flipped", {}),
            ("no_job_inputs", {"job_inputs": None}),
            (
                "unrecognized_table_mode",
                {"job_inputs": {"cdc_ingest_mode": "buffered"}, "cdc_table_mode": "something_new"},
            ),
            ("still_snapshotting", {"job_inputs": {"cdc_ingest_mode": "buffered"}, "cdc_mode": "snapshot"}),
        ]
    )
    def test_the_scheduled_sync_is_not_forced_off_the_flag_for(self, _name, overrides):
        assert scheduled_sync_consumes_buffer(_schema(**overrides)) is False


@pytest.mark.asyncio
class TestMultiLaneDeletionFloor:
    """A file is deletable only once EVERY lane has committed past it.

    A `both` schema serves its two tables on alternating runs, so the consolidated lane routinely
    runs ahead. Deleting on its position alone would drop files the companion never appended.
    """

    async def _floor(
        self, positions: dict[str, int | None], lanes: list[str], applied_rows: dict[str, int] | None = None
    ) -> int | None:
        manager = CDCSourceManager(
            inputs=MagicMock(team_id=_TEAM_ID, schema_id=_SCHEMA_ID), logger=AsyncMock(), lane_resource_names=lanes
        )
        config = {
            "cdc_load_position": {name: pos for name, pos in positions.items() if pos is not None},
            "cdc_load_rows_at_position": applied_rows or {},
        }
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.database_sync_to_async_pool",
            lambda fn: AsyncMock(return_value=config),
        ):
            return (await manager._read_consume_state("users")).floor

    async def test_the_slowest_lane_sets_the_floor(self):
        floor = await self._floor({"users": 900, "users_cdc": 200}, ["users", "users_cdc"])
        assert floor == 200

    async def test_a_lane_that_has_committed_nothing_holds_every_deletion(self):
        # No position is not position zero: the lane has proven nothing, so nothing may be deleted.
        floor = await self._floor({"users": 900}, ["users", "users_cdc"])
        assert floor is None

    async def test_a_single_lane_schema_uses_its_own_position(self):
        floor = await self._floor({"users": 900}, ["users"])
        assert floor == 900

    async def _own_floor(
        self, positions: dict[str, int], lanes: list[str], applied_rows: dict[str, int] | None = None
    ) -> int | None:
        manager = CDCSourceManager(
            inputs=MagicMock(team_id=_TEAM_ID, schema_id=_SCHEMA_ID), logger=AsyncMock(), lane_resource_names=lanes
        )
        config = {"cdc_load_position": positions, "cdc_load_rows_at_position": applied_rows or {}}
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.database_sync_to_async_pool",
            lambda fn: AsyncMock(return_value=config),
        ):
            return (await manager._read_consume_state("users")).own_floor

    async def test_the_read_skip_floor_also_holds_back_an_owed_position(self):
        # What a lane may stop FETCHING answers to the same rule as what it may delete: skipping a
        # file it still owes rows at would take away the rows its count is spent against.
        own = await self._own_floor({"users": 900}, ["users", "users_cdc"], applied_rows={"users": 3})
        assert own == 899

    async def test_the_read_skip_floor_is_this_lane_not_the_slowest(self):
        # Its whole point is to run ahead of a lane that is holding the file alive.
        own = await self._own_floor({"users": 900, "users_cdc": 200}, ["users", "users_cdc"])
        assert own == 900

    async def test_a_lane_owing_rows_at_its_position_holds_that_position_back(self):
        # The skip counts rows across every file the transaction touches, so none of them may go
        # while the count is non-zero — otherwise it lands on rows that were never applied.
        floor = await self._floor({"users_cdc": 900}, ["users_cdc"], applied_rows={"users_cdc": 3})
        assert floor == 899

    async def test_the_slowest_lane_still_wins_when_the_other_owes_rows(self):
        floor = await self._floor(
            {"users": 200, "users_cdc": 900}, ["users", "users_cdc"], applied_rows={"users_cdc": 3}
        )
        assert floor == 200


@pytest.mark.asyncio
class TestAppliedPrefixSkip:
    """The append lane re-reads a position's rows until the file is deleted.

    A position repeats across every event of its transaction, so only the count of rows already
    applied says where the last run stopped. These prove the reader skips exactly that prefix.
    """

    async def test_rows_already_applied_at_the_position_are_skipped(self):
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1, 2, 3], [200, 200, 200]))})

        tables = await _collect(s3, applied_position=200, applied_rows=2)

        assert tables[0].column("id").to_pylist() == [3]

    async def test_the_skip_spans_files_that_share_the_position(self):
        # One transaction can fill several files; the applied prefix runs across them in order.
        s3 = _FakeS3(
            {
                _key(200, 200, 0): _parquet_bytes(_table([1, 2], [200, 200])),
                _key(200, 200, 1): _parquet_bytes(_table([3, 4], [200, 200])),
            }
        )

        tables = await _collect(s3, applied_position=200, applied_rows=3)

        assert tables[0].column("id").to_pylist() == [4]

    async def test_rows_past_the_position_are_never_skipped(self):
        # The budget is spent on the position's own rows; a later transaction is new ground.
        s3 = _FakeS3({_key(100, 300): _parquet_bytes(_table([1, 2], [200, 300]))})

        tables = await _collect(s3, applied_position=200, applied_rows=5)

        assert tables[0].column("id").to_pylist() == [2]

    async def test_nothing_is_skipped_when_no_rows_are_known_applied(self):
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1, 2], [200, 200]))})

        tables = await _collect(s3, applied_position=200, applied_rows=0)

        assert tables[0].column("id").to_pylist() == [1, 2]


class TestBelowPositionRows:
    """A file that straddles the position carries rows the lane already wrote beneath it.

    They must not reach the loader as history: the loader's own drop is behind a rollout flag, and
    the append lane cannot be correct only when a flag says so.
    """

    async def test_rows_below_the_position_are_dropped_without_spending_the_count(self):
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1, 2, 3, 4], [100, 150, 200, 200]))})

        tables = await _collect(s3, applied_position=200, applied_rows=1)

        assert tables[0].column("id").to_pylist() == [4]

    async def test_the_merge_lane_keeps_rows_below_its_position(self):
        # Its upsert makes them a no-op, and the loader's resolution trims them when it is on.
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1, 2], [100, 200]))})

        tables = await _collect(s3, applied_position=200, applied_rows=0, write_mode=CONSOLIDATED_WRITE_MODE)

        assert tables[0].column("id").to_pylist() == [1, 2]


class TestSkipBudgetAgainstDeletion:
    """The skip counts rows at a position, so every file holding that position must still be there.

    `provable_position` is what keeps them: a lane part-way through a transaction proves only the
    position before it, so nothing at that position is deletable while the count is non-zero.
    """

    async def test_a_file_at_the_applied_position_is_not_deleted_while_rows_are_owed(self):
        # Deleting it would spend the count on the NEXT file's rows, which never landed, and drop
        # them silently.
        s3 = _FakeS3(
            {
                _key(200, 200, 0): _parquet_bytes(_table([1, 2], [200, 200])),
                _key(200, 300, 1): _parquet_bytes(_table([3, 4], [200, 300])),
            }
        )

        tables = await _collect(
            s3,
            load_position=199,
            proof_time=_OLD_MTIME + dt.timedelta(hours=1),
            applied_position=200,
            applied_rows=2,
        )

        assert s3.removed == []
        assert tables[0].column("id").to_pylist() == [3, 4]

    async def test_the_position_clears_for_deletion_once_no_rows_are_owed(self):
        s3 = _FakeS3({_key(200, 200, 0): _parquet_bytes(_table([1, 2], [200, 200]))})

        await _collect(
            s3,
            load_position=200,
            proof_time=_OLD_MTIME + dt.timedelta(hours=1),
            applied_position=200,
            applied_rows=0,
        )

        assert s3.removed == [_key(200, 200, 0)]

    async def test_the_merge_lane_skips_nothing_whatever_the_count_says(self):
        # Its upsert makes a row it already holds a no-op, so it re-reads freely; only the append
        # lane resumes part-way into a transaction.
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1, 2], [200, 200]))})

        tables = await _collect(s3, applied_position=200, applied_rows=2, write_mode=CONSOLIDATED_WRITE_MODE)

        assert tables[0].column("id").to_pylist() == [1, 2]


class TestOwnLaneReadSkip:
    """A lane stops fetching what it has proven it committed, even while the file must survive.

    Files are held until EVERY lane passes them, so on a `both` schema the merge lane would
    otherwise re-read and re-bill the same transaction on each of its turns for as long as the
    append lane owes rows at it.
    """

    async def test_a_file_this_lane_has_proven_is_not_fetched(self):
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1, 2], [200, 200]))})

        tables = await _collect(
            s3,
            load_position=100,  # a slower lane keeps the file alive
            own_floor=200,
            proof_time=_OLD_MTIME + dt.timedelta(hours=1),
            write_mode=CONSOLIDATED_WRITE_MODE,
        )

        assert s3.opened == []
        assert s3.removed == []
        assert tables == []

    async def test_a_file_past_this_lane_is_still_fetched(self):
        s3 = _FakeS3({_key(300, 300): _parquet_bytes(_table([1], [300]))})

        tables = await _collect(
            s3,
            load_position=100,
            own_floor=200,
            proof_time=_OLD_MTIME + dt.timedelta(hours=1),
            write_mode=CONSOLIDATED_WRITE_MODE,
        )

        assert s3.opened == [_key(300, 300)]
        assert tables[0].column("id").to_pylist() == [1]

    async def test_a_file_holding_rows_this_lane_owes_is_still_fetched(self):
        # `provable_position` keeps the append lane's own floor below the position it owes rows at,
        # so the skip can never take away a file the count is about to be spent against.
        s3 = _FakeS3({_key(200, 200): _parquet_bytes(_table([1, 2, 3], [200, 200, 200]))})

        tables = await _collect(
            s3,
            load_position=199,
            own_floor=199,
            proof_time=_OLD_MTIME + dt.timedelta(hours=1),
            applied_position=200,
            applied_rows=2,
        )

        assert s3.opened == [_key(200, 200)]
        assert tables[0].column("id").to_pylist() == [3]

    async def test_nothing_is_skipped_without_a_completed_listing(self):
        # An unproven run drained nothing; re-reading is the safe direction.
        s3 = _FakeS3({_key(100, 200): _parquet_bytes(_table([1], [200]))})

        tables = await _collect(
            s3, load_position=100, own_floor=200, proof_time=None, write_mode=CONSOLIDATED_WRITE_MODE
        )

        assert s3.opened == [_key(100, 200)]
        assert tables[0].column("id").to_pylist() == [1]


class TestBatchesInFlight:
    # Legacy deliveries carry no position column, so a consumer merge racing them can be overwritten
    # by an older row. These prove both backlog forms hold the consumer off.

    def test_deferred_runs_are_a_backlog_without_touching_the_queue(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.psycopg"
        ) as mock_psycopg:
            assert has_batches_in_flight(_schema(sync_type_config={"cdc_deferred_runs": [{"x": 1}]})) is True
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
            assert has_batches_in_flight(schema) is expected


@pytest.mark.asyncio
class TestListingProof:
    # The deletion proof must come only from a run that listed the buffer AND completed. A gated
    # no-op run (which never lists) or a crashed run (whose job never completes) must prove nothing.

    async def test_every_consuming_run_stamps_its_listing(self):
        s3 = _FakeS3({_key(100, 199): _parquet_bytes(_table([1], [100]))})

        with _patched(s3, None, None) as mock_stamp:
            [t async for t in _manager().get_items("users", write_mode=COMPANION_WRITE_MODE)]

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
