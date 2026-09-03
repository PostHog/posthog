import datetime as dt
import contextlib

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    CDC_SEQ_PROVENANCE,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import build_buffer_file_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position import LanePosition
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
    COMPANION_WRITE_MODE,
    CONSOLIDATED_WRITE_MODE,
    CDCLane,
    CDCSourceManager,
    ReplayFilter,
    build_output_lanes,
    companion_resource_name,
    consumes_buffer,
    has_batches_in_flight,
    scheduled_sync_consumes_buffer,
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


def _ops(ids: list[int], seqs: list[int], ops: list[str] | None = None) -> pa.Table:
    """A batch as the lanes see it: keyed rows carrying the position and the operation."""
    return _table(ids, seqs).append_column(
        pa.field(CDC_OP_COLUMN, pa.string()), pa.array(ops or ["I"] * len(ids), pa.string())
    )


_NO_POSITION = LanePosition(position=None, applied={})


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
        missing_keys: set[str] | None = None,
    ) -> None:
        self.files = dict(files)
        # Listed but gone by the time the reader opens them, as a concurrent retry leaves things.
        self.missing_keys = missing_keys or set()
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
        if key in self.missing_keys or key not in self.files:
            raise FileNotFoundError(key)
        data = self.files[key]

        @contextlib.asynccontextmanager
        async def _reader():
            handle = AsyncMock()
            handle.read = AsyncMock(return_value=data)
            yield handle

        return _reader()


@contextlib.contextmanager
def _patched(s3: _FakeS3):
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.aget_s3_client"
        ) as mock_client,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.get_buffer_prefix",
            return_value=f"s3://{_PREFIX}",
        ),
    ):
        mock_client.return_value.__aenter__ = AsyncMock(return_value=s3)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        yield


def _manager(*, deletion_floor: int | None = None) -> CDCSourceManager:
    inputs = MagicMock()
    inputs.team_id = _TEAM_ID
    inputs.schema_id = _SCHEMA_ID
    inputs.reset_pipeline = False
    return CDCSourceManager(inputs=inputs, logger=AsyncMock(), deletion_floor=deletion_floor)


async def _collect(s3: _FakeS3, *, deletion_floor: int | None = None, **kwargs) -> list[pa.Table]:
    with _patched(s3):
        return [t async for t in _manager(deletion_floor=deletion_floor).get_items(**kwargs)]


def _schema(**overrides) -> MagicMock:
    schema = MagicMock()
    schema.is_cdc = overrides.get("is_cdc", True)
    schema.cdc_mode = overrides.get("cdc_mode", "streaming")
    schema.cdc_table_mode = overrides.get("cdc_table_mode", "consolidated")
    schema.initial_sync_complete = overrides.get("initial_sync_complete", True)
    schema.sync_type_config = overrides.get("sync_type_config", {})
    schema.source.job_inputs = overrides.get("job_inputs", {})
    schema.primary_key_columns = overrides.get("primary_key_columns", ["id"])
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
            ("job_inputs_not_a_mapping", {"job_inputs": "buffered"}),
            ("still_snapshotting", {"job_inputs": {"cdc_ingest_mode": "buffered"}, "cdc_mode": "snapshot"}),
        ]
    )
    def test_the_scheduled_sync_is_not_forced_off_the_flag_for(self, _name, overrides):
        assert scheduled_sync_consumes_buffer(_schema(**overrides)) is False


@pytest.mark.asyncio
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
class TestReplayFilter:
    """What a lane drops when a run re-reads a buffer its table has partly consumed.

    Both lanes run the same filter and differ only in what they asked the position for. A merge
    asks for no identity, so nothing at the position matches and every row there is rewritten as
    an upsert. History asks for the rows its table holds there, so it drops exactly those.
    """

    @staticmethod
    def _append(position, applied):
        return ReplayFilter(LanePosition(position=position, applied=applied, key_columns=("id", CDC_OP_COLUMN)))

    @staticmethod
    def _merge(position):
        return ReplayFilter(LanePosition(position=position, applied={}, key_columns=()))

    def test_nothing_is_dropped_before_a_lane_has_written_anything(self):
        table = _ops([1, 2], [10, 20], ["I", "U"])

        assert self._append(None, {}).apply(table) is table
        assert self._merge(None).apply(table) is table

    def test_rows_below_the_position_are_dropped(self):
        result = self._merge(20).apply(_ops([1, 2, 3], [10, 20, 30]))

        assert result.column(CDC_SEQ_COLUMN).to_pylist() == [20, 30]

    def test_the_merge_lane_keeps_every_row_at_its_position(self):
        result = self._merge(20).apply(_ops([1, 2, 3], [20, 20, 30]))

        assert result.column("id").to_pylist() == [1, 2, 3]

    def test_the_append_lane_drops_only_the_rows_its_table_already_holds(self):
        result = self._append(20, {(1, "I"): 1, (2, "U"): 1}).apply(
            _ops([1, 2, 3, 4], [20, 20, 20, 30], ["I", "U", "I", "U"])
        )

        assert result.column("id").to_pylist() == [3, 4]

    def test_a_file_that_arrives_late_at_a_consumed_position_still_lands(self):
        """The data-loss case a bare count could not see.

        The previous run read every file at position 20 and its table holds those two rows.
        Capture then wrote another file at the same position, carrying rows nothing has seen.
        """
        result = self._append(20, {(1, "I"): 1, (2, "I"): 1}).apply(_ops([7, 8], [20, 20], ["I", "I"]))

        assert result.column("id").to_pylist() == [7, 8]

    def test_a_key_changed_twice_in_one_transaction_keeps_its_second_version(self):
        result = self._append(20, {(1, "U"): 1}).apply(_ops([1, 1], [20, 20], ["U", "U"]))

        assert result.num_rows == 1

    def test_the_identity_is_spent_across_files_that_share_the_position(self):
        replay = self._append(20, {(1, "I"): 1, (2, "I"): 1})

        first = replay.apply(_ops([1], [20], ["I"]))
        second = replay.apply(_ops([2, 3], [20, 20], ["I", "I"]))

        assert first.num_rows == 0
        assert second.column("id").to_pylist() == [3]

    def test_rows_past_the_position_are_never_matched(self):
        replay = self._append(20, {(1, "I"): 1})
        result = replay.apply(_ops([1, 2], [30, 40], ["I", "I"]))

        assert result.column("id").to_pylist() == [1, 2]
        assert replay.rows_skipped == 0

    def test_a_table_missing_a_key_column_keys_the_batch_the_same_way(self):
        # The position reports the columns it actually read. If the filter keyed batch rows by a
        # wider tuple than the table was read with, nothing would ever match and every replayed
        # row would be appended a second time.
        replay = ReplayFilter(LanePosition(position=20, applied={("I",): 1}, key_columns=(CDC_OP_COLUMN,)))

        result = replay.apply(_ops([1, 2], [20, 20], ["I", "I"]))

        assert result.num_rows == 1

    def test_skipped_rows_are_counted(self):
        replay = self._append(20, {(2, "I"): 1})
        replay.apply(_ops([1, 2, 3], [10, 20, 20], ["I", "I", "I"]))

        assert replay.rows_skipped == 2


@pytest.mark.asyncio
class TestFloorDeletion:
    """Files every table has settled are deleted before they are read, never after."""

    async def test_files_strictly_below_the_floor_are_deleted_and_never_read(self):
        s3 = _FakeS3({_key(1, 10): _parquet_bytes(_table([1], [10])), _key(21, 30): _parquet_bytes(_table([2], [30]))})
        await _collect(s3, deletion_floor=20)

        assert s3.removed == [_key(1, 10)]
        assert s3.opened == [_key(21, 30)]

    async def test_a_file_at_the_floor_is_re_read_rather_than_deleted(self):
        # Position alone cannot tell a consumed file from the unread tail of a transaction split
        # across files. The replay filter drops its rows, so the re-read writes and bills nothing.
        s3 = _FakeS3({_key(11, 20): _parquet_bytes(_table([1], [20]))})
        await _collect(s3, deletion_floor=20)

        assert s3.removed == []
        assert s3.opened == [_key(11, 20)]

    async def test_nothing_is_deleted_before_every_lane_has_a_position(self):
        s3 = _FakeS3({_key(1, 10): _parquet_bytes(_table([1], [10]))})
        await _collect(s3, deletion_floor=None)

        assert s3.removed == []


@pytest.mark.asyncio
class TestBuildOutputLanes:
    @staticmethod
    async def _build(schema, positions: list[LanePosition]):
        delta_ref = MagicMock()
        delta_ref.return_value.get_delta_table = AsyncMock(return_value=MagicMock())
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.DeltaTableRef", delta_ref
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.ensure_position_stats",
                AsyncMock(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.read_lane_position",
                AsyncMock(side_effect=positions),
            ),
        ):
            return await build_output_lanes(schema, MagicMock(), AsyncMock())

    async def test_both_writes_two_tables_in_one_run(self):
        lanes, _ = await self._build(_schema(cdc_table_mode="both"), [_NO_POSITION, _NO_POSITION])

        assert [lane.name for lane in lanes] == ["users", "users_cdc"]
        assert [lane.cdc_write_mode for lane in lanes] == [CONSOLIDATED_WRITE_MODE, COMPANION_WRITE_MODE]

    @parameterized.expand([("consolidated", "consolidated", "users"), ("cdc_only", "cdc_only", "users_cdc")])
    async def test_a_single_table_mode_bills_its_only_lane(self, _name, table_mode, expected):
        lanes, _ = await self._build(_schema(cdc_table_mode=table_mode), [_NO_POSITION])

        assert [(lane.name, lane.billable) for lane in lanes] == [(expected, True)]

    async def test_both_bills_the_consolidated_lane_only(self):
        lanes, _ = await self._build(_schema(cdc_table_mode="both"), [_NO_POSITION, _NO_POSITION])

        assert [(lane.name, lane.billable) for lane in lanes] == [("users", True), ("users_cdc", False)]

    async def test_only_the_append_lane_matches_rows_at_the_position(self):
        lanes, _ = await self._build(
            _schema(cdc_table_mode="both"),
            [
                LanePosition(position=20, applied={}),
                LanePosition(
                    position=20,
                    applied={(1, "I"): 1, (2, "I"): 1, (3, "I"): 1},
                    key_columns=("id", CDC_OP_COLUMN),
                ),
            ],
        )

        batch = _ops([1, 2, 3, 4], [20, 20, 20, 30], ["I", "I", "I", "I"])
        merged, history = (lane.transform(batch) for lane in lanes)

        assert merged.column("id").to_pylist() == [1, 2, 3, 4]
        assert history.column("id").to_pylist() == [4]

    async def test_the_floor_is_the_lowest_position_any_table_holds(self):
        _, floor = await self._build(
            _schema(cdc_table_mode="both"),
            [LanePosition(position=50, applied={}), LanePosition(position=20, applied={})],
        )

        assert floor == 20

    async def test_a_lane_with_no_position_holds_the_floor_open(self):
        _, floor = await self._build(
            _schema(cdc_table_mode="both"), [LanePosition(position=50, applied={}), _NO_POSITION]
        )

        assert floor is None
