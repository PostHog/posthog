"""Consume the S3 change buffer on the normal scheduled sync.

The egress half of buffered CDC: capture writes position-named Parquet files (see `buffer.py`) and
this reads them back as an ordinary source, so change events reach the loader through the same path
every other source uses.

Files are deleted by the loader once the job that drained them completes, never on yield — the v3
batcher buffers across generator yields, so a yielded table can still be in memory when the
generator resumes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Final, Literal

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    SCD2_VALID_TO_COLUMN,
    companion_resource_name as build_companion_resource_name,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    BufferFileSpan,
    get_buffer_prefix,
    parse_buffer_file_name,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position import (
    LanePosition,
    ensure_position_stats,
    read_lane_position,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import (
    SCD2_APPEND_MODE,
    drop_superseded_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import parse_ingest_mode
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import resolve_table_and_folder_names
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.batching import (
    DEFAULT_BATCH_BYTE_LIMIT,
    DEFAULT_BATCH_ROW_LIMIT,
    TableBatcher,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import OutputLane, SourceInputs

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

CONSOLIDATED_TABLE_MODE = "consolidated"
CDC_ONLY_TABLE_MODE = "cdc_only"
BOTH_TABLE_MODE = "both"

# The loader's write mode per lane, and the flag that tells the pipeline a run carries change
# events rather than rows read from a table.
CDCWriteMode = Literal["incremental_merge", "scd2_append"]
CONSOLIDATED_WRITE_MODE: Final = "incremental_merge"
COMPANION_WRITE_MODE: Final = SCD2_APPEND_MODE

# The tables each mode's change stream feeds, as the write mode the loader uses for each — in the
# order the legacy extraction path writes them. A mode absent here is one this module cannot write.
_LANE_WRITE_MODES: dict[str, tuple[CDCWriteMode, ...]] = {
    CONSOLIDATED_TABLE_MODE: (CONSOLIDATED_WRITE_MODE,),
    CDC_ONLY_TABLE_MODE: (COMPANION_WRITE_MODE,),
    BOTH_TABLE_MODE: (CONSOLIDATED_WRITE_MODE, COMPANION_WRITE_MODE),
}


@frozen
class CDCLane:
    """One warehouse table this schema's change stream feeds, and how the loader writes it."""

    resource_name: str
    write_mode: CDCWriteMode


def serves_buffered_lane(schema: ExternalDataSchema) -> bool:
    """Schema-side conditions for buffered ingress; the source's `ingest_mode` is the other half.

    Fails closed on every axis: a table mode with no lanes, or a schema with no table yet, stays on
    the legacy extraction path.
    """
    return bool(
        schema.is_cdc
        and schema.cdc_mode == "streaming"
        and schema.cdc_table_mode in _LANE_WRITE_MODES
        and schema.initial_sync_complete
    )


def consumes_buffer(schema: ExternalDataSchema, *, ingest_mode: str) -> bool:
    """Whether this schema's changes are delivered through the buffer."""
    return ingest_mode == "buffered" and serves_buffered_lane(schema)


def companion_resource_name(schema: ExternalDataSchema) -> str:
    """Storage name for this schema's `_cdc` companion — the same table capture and the seed write."""
    return build_companion_resource_name(schema.name)


def served_lanes(schema: ExternalDataSchema) -> list[CDCLane]:
    """The tables this schema's change stream feeds.

    One entry per Delta table the mode writes, in the order the legacy extraction path writes them.
    An unrecognized mode returns nothing, which reads as "not a lane the buffer serves".
    """
    return [
        CDCLane(
            resource_name=(
                companion_resource_name(schema) if mode == COMPANION_WRITE_MODE else consolidated_resource_name(schema)
            ),
            write_mode=mode,
        )
        for mode in _LANE_WRITE_MODES.get(schema.cdc_table_mode, ())
    ]


async def build_output_lanes(
    schema: ExternalDataSchema, job: ExternalDataJob, logger: FilteringBoundLogger
) -> tuple[list[OutputLane], int | None]:
    """Every table this run writes, and the position below which the buffer is settled.

    One run serves them all from one read of the buffer. Each carries its own replay filter, built
    from its own table, because a failed run can leave one lane ahead of the other.

    The first lane is the billable one: a change stream feeding two tables is one stream, and
    charging it twice would price the history table as a second sync.

    The floor is the lowest position any lane holds — a file below it is settled for every table.
    A lane whose table reports no position holds the floor open, so nothing is deleted until every
    lane can prove where it stops.
    """
    lanes: list[OutputLane] = []
    positions: list[int | None] = []
    for index, lane in enumerate(served_lanes(schema)):
        delta_table = await DeltaTableRef(lane.resource_name, job, logger).get_delta_table()
        is_append = lane.write_mode == COMPANION_WRITE_MODE
        keys = [normalize_column_name(name) for name in schema.primary_key_columns or []]
        if delta_table is not None:
            # Before the read, so this run's own write is the one that carries the statistic.
            await ensure_position_stats(delta_table, [*keys, *([SCD2_VALID_TO_COLUMN] if is_append else [])])
        key_columns = [*keys, CDC_OP_COLUMN]
        position = await read_lane_position(delta_table, key_columns=key_columns if is_append else None)
        positions.append(position.position)
        replay = ReplayFilter(position)
        lanes.append(
            OutputLane(
                name=lane.resource_name,
                cdc_write_mode=lane.write_mode,
                billable=index == 0,
                transform=replay.apply,
            )
        )
    floor = None if any(p is None for p in positions) else min(p for p in positions if p is not None)
    return lanes, floor


def scheduled_sync_consumes_buffer(schema: ExternalDataSchema) -> bool:
    """Whether this schema's scheduled sync consumes the S3 change buffer.

    Doubles as the pipeline-version override: buffered consumption must run the v3 pipeline,
    because only the v3 loader records the load position that proves buffer files consumed and
    resolves versions and deletes. The team's general rollout flag cannot make that call (it can
    neither see individual sources nor be trusted to stay wide after a flip), so the version
    check consults this predicate before the flag.
    """
    return consumes_buffer(schema, ingest_mode=parse_ingest_mode(schema.source.job_inputs))


def has_batches_in_flight(schema: ExternalDataSchema) -> bool:
    """Whether any delivery for this schema is still working through the queue.

    Two kinds, and the consumer must stand down for both.

    Legacy deliveries carry no position column, so nothing orders them against buffered writes — a
    consumer merge racing them lets an older legacy row land after a newer buffered one.

    A previous attempt of THIS job is the other kind, and it is why the check has to cover buffered
    batches too. The v3 pipeline lock keeps two scheduled runs apart — it is held from the start of
    the workflow until the loader completes the job — but a retried activity runs under the lock its
    own workflow already holds, and a takeover hands the lock to a new job while the old one's
    batches are still queued. Attempts are superseded only when the loader shows no recent
    progress, and the claim gates are scoped per run, so an attempt that died with batches still
    staged has them claimed and written alongside whatever a new attempt reads. The merge lane
    absorbs that as upserts; the append lane writes it as a second copy of the same history.

    Batches only reach a terminal state after their position is recorded, so "nothing in flight"
    is also what makes the resume point safe to read: every commit before it is already visible.

    Runs holding a failed batch are excluded by the query, matching the loader's claim gate — their
    remaining batches can never be claimed, so they cannot write anything to collide with.
    """
    if schema.sync_type_config.get("cdc_deferred_runs"):
        return True

    conn = psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
    try:
        age = BatchQueue.get_oldest_non_terminal_batch_age_seconds(
            conn, team_id=schema.team_id, schema_ids=[str(schema.id)]
        )
    finally:
        conn.close()
    return age is not None


def consolidated_resource_name(schema: ExternalDataSchema) -> str:
    """Storage name for the consolidated table — must match the snapshot pipeline's.

    `name` and folder diverge for rows renamed bare→qualified (`name="public.users"`, folder
    `users`), and targeting the wrong one lands changes in a parallel Delta table no query reads.
    """
    return resolve_table_and_folder_names(schema.name, schema.resolved_s3_folder_name).folder_name


@frozen
class _BufferFile:
    span: BufferFileSpan
    key: str


class ReplayFilter:
    """Drops from each batch what this lane's table already holds, as the run re-reads the buffer.

    Rows below the position are settled for either lane: the position is a commit's highest row,
    so everything beneath it landed in that commit or an earlier one.

    Rows AT the position are one transaction the previous run may have applied only part of, and
    the two lanes want different things from them. A merge rewrites them as upserts, so it asks
    for no identity, `applied` is empty, and every row at the position is kept. A history table
    would keep a second copy, so it asks for the rows its table holds there and drops a batch row
    whose identity is one of them.

    A multiset, not a set: one transaction can change the same key more than once and history
    keeps every version, so each match spends one. A row whose identity is not there has never
    been written, including one in a file capture wrote after the last run listed the buffer.
    """

    def __init__(self, position: LanePosition) -> None:
        self._position = position.position
        self._applied = Counter(position.applied)
        # Taken from the position itself, so the batch is keyed exactly as the table was read.
        self._key_columns = list(position.key_columns)
        self.rows_skipped = 0

    def apply(self, table: pa.Table) -> pa.Table:
        table, dropped = drop_superseded_rows(table, self._position)
        self.rows_skipped += dropped
        if self._position is None or not self._applied or not table.num_rows:
            return table
        return self._drop_already_written(table)

    def _drop_already_written(self, table: pa.Table) -> pa.Table:
        if any(name not in table.column_names for name in self._key_columns):
            # The batch cannot be keyed the way the table was, so nothing can be proven applied.
            return table
        seqs = table.column(CDC_SEQ_COLUMN).to_pylist()
        identities = list(zip(*(table.column(name).to_pylist() for name in self._key_columns)))
        keep: list[int] = []
        for i, seq in enumerate(seqs):
            if seq == self._position and self._applied.get(identities[i], 0) > 0:
                self._applied[identities[i]] -= 1
                continue
            keep.append(i)
        if len(keep) == table.num_rows:
            return table
        self.rows_skipped += table.num_rows - len(keep)
        return table.take(pa.array(keep, type=pa.int64()))


class CDCSourceManager:
    """Reads one schema's buffered change events in position order, deleting what is settled."""

    def __init__(
        self, inputs: SourceInputs, logger: FilteringBoundLogger, *, deletion_floor: int | None = None
    ) -> None:
        self._inputs = inputs
        self._logger = logger
        self._deletion_floor = deletion_floor

    def _is_consumed(self, end_seq: int) -> bool:
        """Whether every table this schema feeds already holds this file's rows.

        Strictly below the floor only. The floor is the lowest position any of the tables holds,
        and lanes apply their batches in order, so every row beneath it landed everywhere.

        A file AT the floor is left alone, because position cannot tell a consumed one from the
        unread tail of a transaction split across files — they all carry one commit position. It
        costs one re-read per tick until a later commit lifts the floor past it, and the replay
        filter drops every row of it, so nothing is written or billed for the re-read.
        """
        return self._deletion_floor is not None and end_seq < self._deletion_floor

    async def _list_buffer_files(self) -> list[_BufferFile]:
        """Buffer files under this schema's prefix, in position order.

        Sorted by the filename's `(start, end, index)` and never by S3 mtime: the position range is
        the ordering token, and mtime would interleave a retry's files with the attempt it replaced.
        Names that don't match the contract are ignored rather than guessed at.
        """
        prefix = get_buffer_prefix(self._inputs.team_id, str(self._inputs.schema_id))

        async with aget_s3_client() as s3:
            try:
                # refresh: capture writes through a different process, so this client's dircache is
                # never invalidated by them — a cached listing could miss files indefinitely.
                ls_res = await s3._ls(prefix, detail=True, refresh=True)
            except FileNotFoundError:
                await self._logger.adebug("cdc_buffer_prefix_not_found", prefix=prefix)
                return []

        ls_values = ls_res.values() if isinstance(ls_res, dict) else ls_res

        files: list[_BufferFile] = []
        for entry in ls_values:
            if entry["type"] == "directory":
                continue
            key = entry["Key"]
            parsed = parse_buffer_file_name(key.rsplit("/", 1)[-1])
            if parsed is None:
                continue
            files.append(_BufferFile(span=parsed, key=key))

        files.sort(key=lambda f: (f.span.start_seq, f.span.end_seq, f.span.file_index))
        await self._logger.adebug("cdc_buffer_files_listed", prefix=prefix, file_count=len(files))
        return files

    async def get_items(
        self,
        *,
        batch_row_limit: int = DEFAULT_BATCH_ROW_LIMIT,
        batch_byte_limit: int = DEFAULT_BATCH_BYTE_LIMIT,
    ) -> AsyncGenerator[pa.Table]:
        """Every buffered change, once, in position order — for all of this schema's lanes.

        One read serves every lane. What each lane already holds is dropped per lane afterwards,
        by the filter `build_output_lanes` gave it, because a failed run can leave one lane ahead
        of the other.

        Files every table has settled are deleted here, before they are read, so the run that
        proves them consumed is never the one that deletes them.
        """
        files = await self._list_buffer_files()
        batch: TableBatcher[str] = TableBatcher(row_limit=batch_row_limit, byte_limit=batch_byte_limit)

        async with aget_s3_client() as s3:
            for file in files:
                # The only place a buffer file is deleted — see `_is_consumed` for the proof.
                if self._is_consumed(file.span.end_seq):
                    await s3._rm(file.key)
                    continue

                try:
                    async with await s3.open_async(file.key, "rb") as f:
                        data = await f.read()
                        table = pq.read_table(pa.BufferReader(data))
                except FileNotFoundError:
                    # A concurrent run, or a retry of this activity, can have deleted the file
                    # between the listing and this open — the listing is a snapshot, not a lease.
                    await self._logger.adebug("cdc_buffer_file_already_consumed", key=file.key)
                    continue

                if table.num_rows == 0:
                    continue

                if batch.add(table):
                    yield self._finalize_batch(batch.tables)
                    batch.reset()

            if batch:
                yield self._finalize_batch(batch.tables)

    def _finalize_batch(self, tables: list[pa.Table]) -> pa.Table:
        # `permissive` because a column added to the source table mid-stream makes later files
        # wider; the loader's schema evolution handles the union.
        return pa.concat_tables(tables, promote_options="permissive")
