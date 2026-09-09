"""Consume the S3 change buffer on the normal scheduled sync.

The egress half of buffered CDC: capture writes position-named Parquet files (see `buffer.py`) and
this reads them back as an ordinary source, so change events reach the loader through the same path
every other source uses.

Files are deleted at the start of the next run, once every table the schema feeds is proven past
them, never on yield — the v3 batcher buffers across generator yields, so a yielded table can still
be in memory when the generator resumes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any, Final, Literal

from django.utils import timezone

import psycopg
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_OP_COLUMN,
    CDC_SEQ_COLUMN,
    SCD2_VALID_TO_COLUMN,
    TOAST_OMITTED_COLUMN,
    build_scd2_table,
    companion_resource_name,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    BufferFileSpan,
    get_buffer_prefix,
    parse_buffer_file_name,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.companion_jobs import COMPANION_JOB_IDS_KEY
from products.warehouse_sources.backend.temporal.data_imports.cdc.lane_position import (
    LanePosition,
    content_columns,
    ensure_position_stats,
    read_lane_position,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import (
    SCD2_APPEND_MODE,
    drop_superseded_rows,
    has_engine_seq,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import parse_ingest_mode
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import resolve_table_and_folder_names
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    CDC_SEQ_GUARD_ROWS_DROPPED_TOTAL,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.batching import (
    DEFAULT_BATCH_BYTE_LIMIT,
    DEFAULT_BATCH_ROW_LIMIT,
    TableBatcher,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.db import db_read_with_retry
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


# In `sync_type_config`. Set by the flip command on each schema it moves to the buffer, cleared by
# its rollback. `cdc_buffered_before` stays after a rollback, so a later flip can tell the
# `_ph_cdc_seq` the buffered lane wrote from a column the source owns.
BUFFERED_LANE_KEY = "cdc_buffered_lane"
BUFFERED_BEFORE_KEY = "cdc_buffered_before"


def buffered_lane_candidate(schema: ExternalDataSchema) -> bool:
    """Whether the flip command may move this schema to the buffer: streaming, seeded, with lanes."""
    return bool(
        schema.is_cdc
        and schema.cdc_mode == "streaming"
        and schema.cdc_table_mode in _LANE_WRITE_MODES
        and schema.initial_sync_complete
    )


def serves_buffered_lane(schema: ExternalDataSchema) -> bool:
    """Schema-side conditions for buffered ingress; the source's `ingest_mode` is the other half.

    Eligibility is opt-in per schema, by the marker the flip command writes. A source flipped
    before history modes were served left its `cdc_only` and `both` schemas on legacy with
    their schedules paused; widening this predicate by mode alone would have capture route
    those schemas into the buffer on deploy, with nothing scheduled to consume it. Consolidated
    schemas on an already-buffered source predate the marker and stay served without it.
    """
    if not buffered_lane_candidate(schema):
        return False
    return schema.cdc_table_mode == "consolidated" or bool(schema.sync_type_config.get(BUFFERED_LANE_KEY))


def consumes_buffer(schema: ExternalDataSchema, *, ingest_mode: str) -> bool:
    """Whether this schema's changes are delivered through the buffer."""
    return ingest_mode == "buffered" and serves_buffered_lane(schema)


def served_lanes(schema: ExternalDataSchema) -> list[CDCLane]:
    """The tables this schema's change stream feeds.

    One entry per Delta table the mode writes, in the order the legacy extraction path writes them.
    An unrecognized mode returns nothing, which reads as "not a lane the buffer serves".
    """
    return [
        CDCLane(
            resource_name=(
                companion_resource_name(schema.name)
                if mode == COMPANION_WRITE_MODE
                else consolidated_resource_name(schema)
            ),
            write_mode=mode,
        )
        for mode in _LANE_WRITE_MODES.get(schema.cdc_table_mode, ())
    ]


# Slack when comparing an S3 mtime against a listing timestamp from our clock, so skew between the
# two can never make a file look older than a listing that in fact never saw it.
_CONSUMED_MTIME_MARGIN = dt.timedelta(minutes=5)

# When a run listed the buffer, kept on that run's own job. Proof only once the job completes.
BUFFER_LISTED_AT_KEY = "cdc_buffer_listed_at"


def read_completed_listing_proof(schema: ExternalDataSchema) -> dt.datetime | None:
    """When the buffer was last listed by a run that went on to complete every table it writes.

    Completion is what proves consumption: it means the generator drained every listed file and
    every staged batch committed. A `both` run completes two jobs, so both have to be COMPLETED —
    the schema's own and its companion — or a file at the floor could be deleted while the history
    table still owed it.

    Both queries are bounded by `created_at`. `externaldatajob` is one of the largest tables in
    this database and a 5-minute schema adds a row every tick, so an unbounded sort over its
    history — or a JSONB predicate with no index across it — would cost more every day it ran.
    A proof older than the window is no loss: it only ever deletes fewer files.
    """
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    since = timezone.now() - _PROOF_WINDOW
    jobs = (
        # `pipeline_id` is redundant with `schema_id` but is what lets the planner use
        # `idx_extdatajob_latest_run` (team, pipeline, status, -created_at); without it the read
        # walks every job the schema ever had, every tick.
        ExternalDataJob.objects.filter(
            team_id=schema.team_id,
            pipeline_id=schema.source_id,
            schema_id=schema.id,
            status=ExternalDataJob.Status.COMPLETED,
            created_at__gte=since,
        )
        .order_by("-created_at")
        .values_list("schema_snapshot", flat=True)[:_PROOF_SEARCH_DEPTH]
    )
    for snapshot in jobs:
        listed_at = (snapshot or {}).get(BUFFER_LISTED_AT_KEY)
        if not listed_at:
            continue
        try:
            stamped = dt.datetime.fromisoformat(listed_at)
        except (TypeError, ValueError):
            continue
        if stamped.tzinfo is None:
            continue
        if _companions_completed((snapshot or {}).get(COMPANION_JOB_IDS_KEY) or []):
            return stamped
    return None


async def completed_listing_proof(schema: ExternalDataSchema) -> dt.datetime | None:
    """`read_completed_listing_proof`, off the event loop."""
    return await database_sync_to_async_pool(db_read_with_retry)(lambda: read_completed_listing_proof(schema))


def clear_listing(job_id: str, team_id: int) -> None:
    """Drop the listing stamp from a job that a retry is about to hand back without draining.

    An earlier attempt of the same job listed the buffer and stamped it; this attempt stood down
    for its in-flight batches, and the workflow will now complete the job anyway. If one of those
    batches then fails in the loader, the job stays Completed, and a stamp still on it would prove
    a listing nothing drained — and delete a file at the floor whose rows never landed.
    """
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    job = ExternalDataJob.objects.filter(id=job_id, team_id=team_id).only("id", "schema_snapshot").first()
    stamped = dict(job.schema_snapshot or {}) if job is not None else {}
    if job is None or not stamped.get(BUFFER_LISTED_AT_KEY):
        return
    snapshot = {k: v for k, v in stamped.items() if k != BUFFER_LISTED_AT_KEY}
    ExternalDataJob.objects.filter(id=job.id).update(schema_snapshot=snapshot)


def _companions_completed(companion_job_ids: list[str]) -> bool:
    """Whether every companion table this run also wrote finished with it."""
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    if not companion_job_ids:
        return True
    statuses = ExternalDataJob.objects.filter(id__in=companion_job_ids).values_list("status", flat=True)
    return len(statuses) == len(companion_job_ids) and all(
        status == ExternalDataJob.Status.COMPLETED for status in statuses
    )


# A run whose companion failed proves nothing, so look past it — but never far: an older listing
# only ever deletes fewer files, and the floor is what does the real work.
_PROOF_SEARCH_DEPTH = 10

# How far back a usable proof can sit. A schema that has not completed a run in this long has a
# bigger problem than an undeleted buffer file.
_PROOF_WINDOW = dt.timedelta(days=2)


def _history_transform(replay: ReplayFilter, key_columns: list[str]) -> Callable[[pa.Table], pa.Table]:
    """Replay first, then stamp the SCD2 validity columns onto what is left.

    Derived here rather than in the loader so the staged parquet is complete on its own: a loader
    on the previous release has no SCD2 step, and would append these rows with no validity at all.
    The legacy extraction path stamps them at the same point for the same reason.

    Replay runs first because `valid_to` points at the next event for the same key. Rows this lane
    already wrote carry their own, and the writer closes them against what arrives next, so
    including them here would both duplicate the row and mis-chain the one that follows it.

    Applied to the coalesced batch the pipeline hands over, never per yield: a key changed in two
    yields of one batch would otherwise leave two rows open.
    """

    def _apply(table: pa.Table) -> pa.Table:
        table = replay.apply(table)
        if not table.num_rows:
            return table
        # No guard on the columns already being there: a source that owns `valid_from` fails
        # loudly inside `build_scd2_table`, where a skip would let the writer close rows against
        # customer data.
        return build_scd2_table(table, key_columns)

    return _apply


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
        # Without primary keys an identity is just the operation, which matches rows the table
        # has never held. Ask for none instead: the lane then replays, which duplicates history
        # rather than losing it, and duplication is the direction that can be repaired.
        key_columns = [*keys, CDC_OP_COLUMN] if keys else None
        position = await read_lane_position(delta_table, key_columns=key_columns if is_append else None)
        positions.append(position.position)
        replay = ReplayFilter(position, team_id=job.team_id)
        lanes.append(
            OutputLane(
                name=lane.resource_name,
                cdc_write_mode=lane.write_mode,
                billable=index == 0,
                transform=_history_transform(replay, keys) if is_append else replay.apply,
            )
        )
    floor = None if any(p is None for p in positions) else min(p for p in positions if p is not None)
    return lanes, floor


def scheduled_sync_consumes_buffer(schema: ExternalDataSchema) -> bool:
    """Whether this schema's scheduled sync consumes the S3 change buffer.

    Doubles as the pipeline-version override: buffered consumption must run the v3 pipeline,
    because only the v3 loader stamps the position each row landed at, which is what the next
    run reads back from the table, and only it resolves versions and deletes. The team's general
    rollout flag cannot make that call (it can neither see individual sources nor be trusted to
    stay wide after a flip), so the version check consults this predicate before the flag.
    """
    return consumes_buffer(schema, ingest_mode=parse_ingest_mode(schema.source.job_inputs))


def has_batches_in_flight(schema: ExternalDataSchema) -> bool:
    """Whether any delivery for this schema is still working through the queue.

    Two kinds, and the consumer must stand down for both.

    Legacy deliveries carry no position column, so nothing orders them against buffered writes — a
    consumer merge racing them lets an older legacy row land after a newer buffered one.

    A previous attempt of THIS job is the other kind, and it is why the check has to cover buffered
    batches too. It sees an attempt only once that attempt has staged a batch: one timed out by
    its heartbeat but still alive inside the listing can stage after this check passed. The busy
    gate keeps the two loads apart, but the history lane then holds both copies. Legacy has the
    same window; fencing batches by attempt in the producer is the follow-up.

    The v3 pipeline lock keeps two scheduled runs apart — it is held from the start of
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
    modified: dt.datetime | None


class ReplayFilter:
    """Drops from each batch what this lane's table already holds, as the run re-reads the buffer.

    Rows below the position are settled for either lane: the position is a commit's highest row,
    so everything beneath it landed in that commit or an earlier one.

    Rows AT the position are one transaction the previous run may have applied only part of, and
    the two lanes want different things from them. A merge rewrites them as upserts, so it asks
    for no identity, `applied` is empty, and every row at the position is kept — dropping one
    would lose a later event for a key the table happens to hold at that same commit. A history
    table would keep a second copy instead, so it asks for the rows its table holds there and
    drops a batch row whose identity is one of them.

    Matched on content, not on key alone: one transaction can change the same key more than once,
    and history keeps every version. Two such changes share every key column and the position,
    so a batch row spends a table row only when their values agree — on every column the batch
    row actually carries, since a TOAST-omitted column is unset in the batch and real in the
    table. A row nothing matches has never been written, including one in a file capture wrote
    after the last run listed the buffer, and including the second change to a key whose first
    change is all the table holds.

    One case content cannot settle: two changes to one key in one transaction with identical
    content — an idempotent second update. If the file holding the first was consumed and
    deleted before the second arrived, the second spends the single stored row and is dropped.
    It is one row of history that adds nothing to the current state; a per-row ordinal from
    capture would close it, and is the follow-up.
    """

    def __init__(self, position: LanePosition, *, team_id: int | None = None) -> None:
        self._position = position.position
        self._applied = {key: list(rows) for key, rows in position.applied.items()}
        # Taken from the position itself, so the batch is keyed exactly as the table was read.
        self._key_columns = list(position.key_columns)
        self._content_schema = position.content_schema
        self._content_matched = position.content_matched
        self._load_applied = position.load_applied
        self._team_id = team_id
        self.rows_skipped = 0

    def apply(self, table: pa.Table) -> pa.Table:
        table, dropped = drop_superseded_rows(table, self._position)
        self._count_skipped(dropped, "superseded")
        if self._position is None or not table.num_rows or (not self._applied and self._load_applied is None):
            return table
        return self._drop_already_written(table)

    def _resolve_applied(self) -> None:
        # Deferred to the first batch that holds a row at the position: on an idle tick there is
        # none, and the table's rows there are never read.
        if self._load_applied is None:
            return
        resolved = self._load_applied()
        self._load_applied = None
        self._applied = {key: list(rows) for key, rows in resolved.applied.items()}
        self._content_schema = resolved.content_schema
        self._content_matched = resolved.content_matched

    def _count_skipped(self, dropped: int, reason: str) -> None:
        # `superseded` is the series the loader raised while the position lived there. It now
        # comes from the extraction workers, so a dashboard filtered to the load fleet loses it.
        self.rows_skipped += dropped
        if dropped and self._team_id is not None:
            CDC_SEQ_GUARD_ROWS_DROPPED_TOTAL.labels(team_id=str(self._team_id), reason=reason).inc(dropped)

    def _drop_already_written(self, table: pa.Table) -> pa.Table:
        # A source column of the same name is customer data, so comparing it against this lane's
        # position would drop rows nothing has written. `drop_superseded_rows` refuses it too.
        if not has_engine_seq(table):
            return table
        if any(name not in table.column_names for name in self._key_columns):
            # The batch cannot be keyed the way the table was, so nothing can be proven applied.
            return table
        # Only rows at the position can match anything, and they sit in a run's first batch;
        # materializing the rest as Python objects would cost every batch for nothing.
        mask = pc.equal(table.column(CDC_SEQ_COLUMN), pa.scalar(self._position, pa.int64()))
        if not pc.any(mask).as_py():
            return table
        candidates = [i for i, hit in enumerate(mask.to_pylist()) if hit]
        self._resolve_applied()
        if not self._applied:
            return table
        at_position = table.take(pa.array(candidates, type=pa.int64()))
        identities = list(zip(*(at_position.column(name).to_pylist() for name in self._key_columns)))
        # Above the position-row cap the table side carried no content, so none is read here.
        contents, stringly = (
            self._batch_contents(at_position) if self._content_matched else ([{}] * at_position.num_rows, set())
        )
        omitted = (
            at_position.column(TOAST_OMITTED_COLUMN).to_pylist()
            if TOAST_OMITTED_COLUMN in at_position.column_names
            else [None] * at_position.num_rows
        )
        ops = at_position.column(CDC_OP_COLUMN).to_pylist() if CDC_OP_COLUMN in at_position.column_names else []
        dropped: set[int] = set()
        for local, row_index in enumerate(candidates):
            held = self._applied.get(identities[local])
            if not held:
                continue
            skip = set(omitted[local] or ())
            if ops and ops[local] == "D":
                # A delete carries only its key under the default replica identity; the loader
                # filled the rest from the table before storing it. Those nulls are unknowns,
                # not values, the same as a TOAST-omitted column.
                skip |= {name for name, value in contents[local].items() if value is None}
            match = next((j for j, row in enumerate(held) if _same_content(contents[local], row, skip, stringly)), None)
            if match is None:
                continue
            held.pop(match)
            if not held:
                del self._applied[identities[local]]
            dropped.add(row_index)
        if not dropped:
            return table
        self._count_skipped(len(dropped), "already_written")
        keep = [i for i in range(table.num_rows) if i not in dropped]
        return table.take(pa.array(keep, type=pa.int64()))

    def _batch_contents(self, table: pa.Table) -> tuple[list[dict[str, Any]], set[str]]:
        """The batch's content columns as the table stores them, so values compare as equals.

        The batch carries the source's own arrow types and the table the loader's evolved ones;
        a date widened to a timestamp reads back as a different Python value. A column that will
        not cast is compared by its string form instead, so two changes that differ only there
        still compare different: dropping it would make a wrong match likelier, and a wrong match
        is a lost change where a missed one is only a copy.
        """
        names = content_columns(table.column_names)
        if self._content_schema is None:
            return table.select(names).to_pylist(), set()
        columns: list[pa.ChunkedArray] = []
        stringly: set[str] = set()
        for name in names:
            column = table.column(name)
            if name in self._content_schema.names:
                try:
                    column = column.cast(self._content_schema.field(name).type)
                except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
                    stringly.add(name)
            columns.append(column)
        return pa.table(columns, names=names).to_pylist(), stringly


def _same_content(batch_row: dict[str, Any], held_row: dict[str, Any], skip: set[str], stringly: set[str]) -> bool:
    """Whether a batch row and a stored row agree on every column the batch row carries."""
    for name, value in batch_row.items():
        if name in skip or name not in held_row:
            continue
        held = held_row[name]
        if name in stringly:
            if str(value) != str(held):
                return False
        elif held != value:
            return False
    return True


class CDCSourceManager:
    """Reads one schema's buffered change events in position order, deleting what is settled."""

    def __init__(
        self,
        inputs: SourceInputs,
        logger: FilteringBoundLogger,
        *,
        deletion_floor: int | None = None,
        proof_time: dt.datetime | None = None,
    ) -> None:
        self._inputs = inputs
        self._logger = logger
        self._deletion_floor = deletion_floor
        self._proof_time = proof_time

    def _is_consumed(self, end_seq: int, modified: dt.datetime | None) -> bool:
        """Whether every table this schema feeds already holds this file's rows.

        Strictly below the floor is position-proof: the lowest-placed lane holds a commit above it,
        and lanes apply their batches in order, so every row beneath landed everywhere.

        AT the floor, position alone cannot tell a consumed file from the unread tail of a
        transaction split across files — they all carry one commit position. A file that already
        existed when a run listed the buffer, and that run then COMPLETED, was read and written by
        it. The margin absorbs clock skew between S3 and our own clock.
        """
        floor = self._deletion_floor
        if floor is None or end_seq > floor:
            return False
        if end_seq < floor:
            return True
        if modified is None or modified.tzinfo is None or self._proof_time is None:
            return False
        return modified < self._proof_time - _CONSUMED_MTIME_MARGIN

    async def stamp_listing(self, listed_at: dt.datetime) -> None:
        """Record on this run's own job that it listed the buffer, before any file is read.

        Kept on the job rather than beside the schema's settings: it describes one run, and it is
        that run's completion which turns it into proof. A crash leaves the job un-completed, so a
        partial run can never prove anything, and a no-op tick never lists and never stamps.
        """
        from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

        def _stamp() -> None:
            job = ExternalDataJob.objects.get(id=self._inputs.job_id, team_id=self._inputs.team_id)
            snapshot = dict(job.schema_snapshot or {})
            snapshot[BUFFER_LISTED_AT_KEY] = listed_at.isoformat()
            # Field-scoped: job completion writes status and finished_at, never the snapshot.
            ExternalDataJob.objects.filter(id=job.id).update(schema_snapshot=snapshot)

        await database_sync_to_async_pool(db_read_with_retry)(_stamp)

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
            modified = entry.get("LastModified")
            files.append(
                _BufferFile(span=parsed, key=key, modified=modified if isinstance(modified, dt.datetime) else None)
            )

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
        listed_at = dt.datetime.now(tz=dt.UTC)
        files = await self._list_buffer_files()
        await self.stamp_listing(listed_at)
        batch: TableBatcher[str] = TableBatcher(row_limit=batch_row_limit, byte_limit=batch_byte_limit)

        async with aget_s3_client() as s3:
            for file in files:
                # The only place a buffer file is deleted — see `_is_consumed` for the proof.
                if self._is_consumed(file.span.end_seq, file.modified):
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
