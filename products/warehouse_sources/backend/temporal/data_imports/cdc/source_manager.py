"""Consume the S3 change buffer on the normal scheduled sync.

The egress half of buffered CDC: capture writes position-named Parquet files (see `buffer.py`) and
this reads them back as an ordinary source, so change events reach the loader through the same path
every other source uses.

Files are deleted by the loader once the job that drained them completes, never on yield — the v3
batcher buffers across generator yields, so a yielded table can still be in memory when the
generator resumes.
"""

from __future__ import annotations

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
    CDC_SEQ_COLUMN,
    companion_resource_name as build_companion_resource_name,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    BufferFileSpan,
    get_buffer_prefix,
    parse_buffer_file_name,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position import read_lane_position
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import SCD2_APPEND_MODE
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import parse_ingest_mode
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


# Each lane's batches are their own run in the queue, which keys idempotency, staging paths and
# claim ordering on the run id. Buffered CDC is the only source feeding more than one table from
# one read, so it is the only one that suffixes.
_LANE_RUN_SUFFIX: dict[CDCWriteMode, str] = {
    CONSOLIDATED_WRITE_MODE: "-consolidated",
    COMPANION_WRITE_MODE: "-cdc",
}


async def build_output_lanes(
    schema: ExternalDataSchema, job: ExternalDataJob, logger: FilteringBoundLogger
) -> list[OutputLane]:
    """Every table this run writes, in the order the legacy extraction path writes them.

    One run serves them all from one read of the buffer. Each carries its own resume point, read
    from its own table, because a failed run can leave one lane ahead of the other.

    The first lane is the billable one: a change stream feeding two tables is one stream, and
    charging it twice would price the history table as a second sync.
    """
    lanes: list[OutputLane] = []
    for index, lane in enumerate(served_lanes(schema)):
        delta_table = await DeltaTableRef(lane.resource_name, job, logger).get_delta_table()
        position = await read_lane_position(delta_table)
        resume = LaneResumeFilter(
            position.position,
            position.rows_at_position if lane.write_mode == COMPANION_WRITE_MODE else 0,
        )
        lanes.append(
            OutputLane(
                name=lane.resource_name,
                cdc_write_mode=lane.write_mode,
                run_uuid_suffix=_LANE_RUN_SUFFIX[lane.write_mode],
                billable=index == 0,
                transform=resume.apply,
            )
        )
    return lanes


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


def _drop_applied_rows(table: pa.Table, position: int, remaining: int) -> tuple[pa.Table, int]:
    """Drop what this lane already wrote: everything below `position`, and `remaining` rows at it.

    Below the position is settled outright — the position only ever advances on a commit, and
    it is that commit's highest row, so every row beneath it landed in that batch or an earlier
    one. A file that straddles the position carries such rows alongside the ones still owed.

    At the position, the rows are the tail of one transaction the previous run may have applied
    only part of. They are read in the same order every run — files sort by position and index,
    row order within a file is fixed — so the count already applied names a prefix, and what
    follows it is the unapplied remainder. Only that prefix spends the count.

    Done here rather than left to the loader's resolution: that is behind a rollout flag, and
    the append lane cannot be correct only when a flag says so.
    """
    if not table.num_rows:
        return table, 0
    # A null position cannot be placed against the prefix, so it is always kept. Engine-stamped
    # batches never carry one (see `has_engine_seq`); a source column of the same name is not
    # engine-stamped and never reaches a lane.
    seqs = table.column(CDC_SEQ_COLUMN).to_pylist()
    keep: list[int] = []
    dropped_at_position = 0
    for i, seq in enumerate(seqs):
        if seq is not None and seq < position:
            continue
        if seq == position and dropped_at_position < remaining:
            dropped_at_position += 1
            continue
        keep.append(i)
    if len(keep) == table.num_rows:
        return table, 0
    return table.take(pa.array(keep, type=pa.int64())), dropped_at_position


class LaneResumeFilter:
    """Drops from each batch what this lane's table already holds, as the run re-reads the buffer.

    A run that failed part-way leaves its lane holding a prefix of the ordered change stream, and
    the next run reads that stream from the start. Every lane skips what sits below its position.
    Only the append lane also skips rows AT it: a merge writes a row it already holds as a no-op,
    while a history table would keep a second copy of it.
    """

    def __init__(self, position: int | None, rows_at_position: int) -> None:
        self._position = position
        self._remaining = rows_at_position
        self.rows_skipped = 0

    def apply(self, table: pa.Table) -> pa.Table:
        if self._position is None or not table.num_rows:
            return table
        before = table.num_rows
        table, dropped_at_position = _drop_applied_rows(table, self._position, self._remaining)
        self._remaining -= dropped_at_position
        self.rows_skipped += before - table.num_rows
        return table


class CDCSourceManager:
    """Reads one schema's buffered change events in position order."""

    def __init__(self, inputs: SourceInputs, logger: FilteringBoundLogger) -> None:
        self._inputs = inputs
        self._logger = logger
        # Names of the files this run read, in the order it read them. The run's final batches
        # carry them, and the loader deletes them once the job completes — see `drained_files`.
        self._drained_files: list[str] = []

    @property
    def drained_files(self) -> list[str]:
        """Buffer files this run read to the end, safe to delete once its job completes.

        Named one by one rather than bounded by a position: capture flushes a transaction bigger
        than its budget across several files that all share one commit position, so "everything up
        to this position" can name a file written after the listing and never read.
        """
        return list(self._drained_files)

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
        """
        files = await self._list_buffer_files()
        batch: TableBatcher[str] = TableBatcher(row_limit=batch_row_limit, byte_limit=batch_byte_limit)

        async with aget_s3_client() as s3:
            for file in files:
                try:
                    async with await s3.open_async(file.key, "rb") as f:
                        data = await f.read()
                        table = pq.read_table(pa.BufferReader(data))
                except FileNotFoundError:
                    # A retry of this activity can have deleted the file between the listing and
                    # this open — the listing is a snapshot, not a lease.
                    await self._logger.adebug("cdc_buffer_file_already_consumed", key=file.key)
                    continue

                # Recorded on the read, not on the yield: the batcher holds tables across yields,
                # and the deletion this feeds waits for the job to complete anyway.
                self._drained_files.append(file.key.rsplit("/", 1)[-1])

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
