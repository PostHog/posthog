"""Consume the S3 change buffer on the normal scheduled sync.

The egress half of buffered CDC: capture writes position-named Parquet files (see `buffer.py`) and
this reads them back as an ordinary source, so change events reach the loader through the same path
every other source uses.

Files are deleted once the persisted load position proves their rows are committed, never on yield —
the v3 batcher buffers across generator yields, so a yielded table can still be in memory when the
generator resumes.
"""

from __future__ import annotations

import uuid
import datetime as dt
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Final, Literal

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.sync import database_sync_to_async_pool

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
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import (
    SCD2_APPEND_MODE,
    read_load_position,
    read_load_state,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import parse_ingest_mode
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import resolve_table_and_folder_names
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.batching import (
    DEFAULT_BATCH_BYTE_LIMIT,
    DEFAULT_BATCH_ROW_LIMIT,
    TableBatcher,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.db import db_read_with_retry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs

if TYPE_CHECKING:
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


# Slack when comparing an S3 mtime against a listing timestamp from our clock, so skew between the
# two can never make a file look older than a listing that in fact never saw it.
_CONSUMED_MTIME_MARGIN = dt.timedelta(minutes=5)

# Each lane's last buffer listing, `{resource_name: {"listed_at": iso, "job_id": str}}` — a sibling
# of `cdc_load_position`, and keyed the same way. A stamp matures into a deletion proof only if its
# job COMPLETES (see _completed_listing_time).
BUFFER_LISTING_CONFIG_KEY = "cdc_buffer_listing"


def _listing_stamps(sync_type_config: dict | None, *, single_lane: str | None = None) -> dict[str, dict]:
    """The per-lane listing stamps, reading the single-lane shape this key used to hold.

    That shape was a bare stamp rather than a mapping, written when consolidated was the only lane
    the buffer served. `single_lane` names the lane it belongs to, so a schema flipped before this
    change keeps its deletion proof instead of re-merging its trailing file once.
    """
    raw = (sync_type_config or {}).get(BUFFER_LISTING_CONFIG_KEY)
    if not isinstance(raw, dict):
        return {}
    if "listed_at" in raw:
        return {single_lane: raw} if single_lane else {}
    return {name: stamp for name, stamp in raw.items() if isinstance(stamp, dict)}


def _parse_listed_at(raw: object) -> dt.datetime | None:
    """A stamp's `listed_at` as a datetime — comparing the raw ISO strings assumes one offset."""
    if not isinstance(raw, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


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


def select_lane(schema: ExternalDataSchema, *, job_id: str | None = None) -> CDCLane:
    """The lane this run serves, alternating across runs when the schema feeds more than one.

    A pipeline run writes one table: its batches share a run id, a batch-index sequence, an S3
    staging folder and a terminal "final batch" that completes the job. So `both` alternates —
    each table is served every other run, and each keeps its own load position. Buffer files are
    deleted only once every lane has passed them, so alternating delays a deletion, never a
    delivery.

    The cursor is the most recent listing stamp rather than a counter: it is written before the
    run reads anything, so a lane that fails mid-run still yields its turn instead of starving the
    other one.
    """
    lanes = served_lanes(schema)
    if len(lanes) < 2:
        return lanes[0]

    stamps = _listing_stamps(schema.sync_type_config)

    # A retry runs under the same job, and the failed attempt already stamped its lane. Alternating
    # off that stamp would serve the other lane under a job id the first lane also carries, so
    # completing the retry would mature a deletion proof for files the first lane never committed.
    for lane in lanes:
        if job_id is not None and (stamps.get(lane.resource_name) or {}).get("job_id") == str(job_id):
            return lane

    last_served, newest = None, None
    for lane in lanes:
        listed_at = _parse_listed_at((stamps.get(lane.resource_name) or {}).get("listed_at"))
        if listed_at is not None and (newest is None or listed_at > newest):
            last_served, newest = lane.resource_name, listed_at

    for lane in lanes:
        if lane.resource_name != last_served:
            return lane
    return lanes[0]


def scheduled_sync_consumes_buffer(schema: ExternalDataSchema) -> bool:
    """Whether this schema's scheduled sync consumes the S3 change buffer.

    Doubles as the pipeline-version override: buffered consumption must run the v3 pipeline,
    because only the v3 loader records the load position that proves buffer files consumed and
    resolves versions and deletes. The team's general rollout flag cannot make that call (it can
    neither see individual sources nor be trusted to stay wide after a flip), so the version
    check consults this predicate before the flag.
    """
    return consumes_buffer(schema, ingest_mode=parse_ingest_mode(schema.source.job_inputs))


def has_pending_legacy_backlog(schema: ExternalDataSchema) -> bool:
    """Whether legacy-lane deliveries for this schema are still in flight.

    Deferred runs and sourcebatch batches carry no position column, so nothing orders them against
    buffered writes — a consumer merge racing them lets an older legacy row land after a newer
    buffered one. The consumer no-ops until both are drained; buffer files just wait.
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


class CDCSourceManager:
    """Reads one schema's buffered change events in position order."""

    def __init__(
        self, inputs: SourceInputs, logger: FilteringBoundLogger, *, lane_resource_names: list[str] | None = None
    ) -> None:
        self._inputs = inputs
        self._logger = logger
        # Every lane the schema feeds, not just the one this run serves: a file is deletable only
        # once all of them have committed past it. Defaults to the lane being read.
        self._lane_resource_names = lane_resource_names

    def _lanes(self, resource_name: str) -> list[str]:
        return self._lane_resource_names or [resource_name]

    @staticmethod
    def _drop_applied_prefix(table: pa.Table, position: int, remaining: int) -> tuple[pa.Table, int]:
        """Drop the first `remaining` rows of this table that sit at `position`.

        Rows at the position are the tail of one transaction, which the previous run may have
        applied only part of. They are read in the same order every run — files sort by position
        and index, row order within a file is fixed — so the count of rows already applied names
        a prefix, and what follows it is the unapplied remainder.
        """
        if remaining <= 0 or not table.num_rows:
            return table, 0
        seqs = table.column(CDC_SEQ_COLUMN).to_pylist()
        at_position = [i for i, seq in enumerate(seqs) if seq == position]
        dropped = at_position[:remaining]
        if not dropped:
            return table, 0
        skip = set(dropped)
        keep = [i for i in range(table.num_rows) if i not in skip]
        return table.take(pa.array(keep, type=pa.int64())), len(dropped)

    async def _read_consume_state(self, resource_name: str) -> tuple[int | None, dict[str, dict]]:
        """The deletion floor across every lane, and their listing stamps, read once per run.

        The floor is the lowest position any lane has committed, so a file survives until the
        slowest lane has taken it. A lane that has recorded nothing yet has proven nothing, so it
        holds deletion entirely.

        The floor decides which files are still needed, not correctness — `drop_superseded_rows` is
        that, and it re-reads the config per batch on the load side. Reading a stale value here
        costs one redundant file read whose rows the guard then drops.
        """
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        sync_type_config = await database_sync_to_async_pool(db_read_with_retry)(
            lambda: ExternalDataSchema.objects.values_list("sync_type_config", flat=True).get(
                id=self._inputs.schema_id, team_id=self._inputs.team_id
            )
        )
        lanes = self._lanes(resource_name)
        positions = [read_load_position(sync_type_config, lane) for lane in lanes]
        floor = None if any(p is None for p in positions) else min(p for p in positions if p is not None)
        stamps = _listing_stamps(sync_type_config, single_lane=lanes[0] if len(lanes) == 1 else None)
        return floor, stamps

    async def _read_applied_state(self, resource_name: str) -> tuple[int | None, int]:
        """This lane's position and the rows already applied at it, read once per run."""
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        sync_type_config = await database_sync_to_async_pool(db_read_with_retry)(
            lambda: ExternalDataSchema.objects.values_list("sync_type_config", flat=True).get(
                id=self._inputs.schema_id, team_id=self._inputs.team_id
            )
        )
        return read_load_state(sync_type_config, resource_name)

    async def _stamp_listing(self, resource_name: str, listed_at: dt.datetime) -> None:
        """Record that this run listed the buffer for its lane, before any file is read.

        The stamp becomes a deletion proof only once this run's job COMPLETES — see
        `_completed_listing_time`. Crashing after the stamp leaves the job un-completed, so a
        partial run can never prove anything.

        It doubles as the alternation cursor `select_lane` reads, which is why it is written
        up front: a lane that fails mid-run has still taken its turn.
        """
        from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys

        stamp = {"listed_at": listed_at.isoformat(), "job_id": str(self._inputs.job_id)}

        def _merge(config: dict) -> None:
            stamps = _listing_stamps(config, single_lane=resource_name)
            stamps[resource_name] = stamp
            config[BUFFER_LISTING_CONFIG_KEY] = stamps

        await database_sync_to_async_pool(db_read_with_retry)(
            lambda: update_sync_type_config_keys(self._inputs.schema_id, self._inputs.team_id, mutate=_merge)
        )

    async def _earliest_completed_listing(self, resource_name: str, stamps: dict[str, dict]) -> dt.datetime | None:
        """When every lane had last listed the buffer under a run that went on to COMPLETE.

        The earliest of those times, because a file is only proven drained once the slowest lane
        listed it — and None if any lane cannot prove it at all.

        Only a completed run proves consumption: completion means the generator drained every
        listed file and every staged batch committed. A job-status check on the stamped job is what
        keeps a no-op run (the legacy-backlog gate returns an empty response without listing) or a
        crashed run from ever serving as proof.
        """
        times = []
        for lane in self._lanes(resource_name):
            listed_at = await self._completed_listing_time(stamps.get(lane))
            if listed_at is None:
                return None
            times.append(listed_at)
        return min(times) if times else None

    async def _completed_listing_time(self, listing: dict | None) -> dt.datetime | None:
        """When this lane was last listed by a run that went on to COMPLETE, or None."""
        from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

        if not listing:
            return None
        try:
            listed_at = dt.datetime.fromisoformat(listing["listed_at"])
            job_id = uuid.UUID(str(listing["job_id"]))
        except (KeyError, TypeError, ValueError):
            return None
        if listed_at.tzinfo is None:
            return None

        completed = await database_sync_to_async_pool(db_read_with_retry)(
            lambda: ExternalDataJob.objects.filter(
                id=job_id, team_id=self._inputs.team_id, status=ExternalDataJob.Status.COMPLETED
            ).exists()
        )
        return listed_at if completed else None

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

    def _is_consumed(
        self,
        end_seq: int,
        modified: dt.datetime | None,
        floor: int | None,
        proof_time: dt.datetime | None,
    ) -> bool:
        """Whether a file's rows are all proven committed, so the file can be deleted.

        Strictly below the floor is position-proof: the load-side guard would drop every row anyway.
        AT the floor, position alone cannot tell a consumed file from the unread tail of a
        transaction split across files (all its rows share one commit position) — but a file that
        already existed at `proof_time` (a completed run's listing) was listed, drained, and
        committed by that run. The margin absorbs clock skew between S3 and our DB; an idle schema's
        trailing file clears it within a couple of ticks instead of being re-merged and re-billed
        forever.
        """
        if floor is None or end_seq > floor:
            return False
        if end_seq < floor:
            return True
        if modified is None or modified.tzinfo is None or proof_time is None:
            return False
        return modified < proof_time - _CONSUMED_MTIME_MARGIN

    async def get_items(
        self,
        resource_name: str,
        batch_row_limit: int = DEFAULT_BATCH_ROW_LIMIT,
        batch_byte_limit: int = DEFAULT_BATCH_BYTE_LIMIT,
    ) -> AsyncGenerator[pa.Table]:
        listed_at = dt.datetime.now(tz=dt.UTC)
        files = await self._list_buffer_files()
        floor, prior_stamps = await self._read_consume_state(resource_name)
        applied_position, applied_rows = await self._read_applied_state(resource_name)
        # Proof comes from the PRIOR stamps, resolved before this run overwrites its lane's.
        proof_time = await self._earliest_completed_listing(resource_name, prior_stamps) if floor is not None else None
        await self._stamp_listing(resource_name, listed_at)

        batch: TableBatcher[str] = TableBatcher(row_limit=batch_row_limit, byte_limit=batch_byte_limit)

        async with aget_s3_client() as s3:
            for file in files:
                key = file.key
                # The only place a buffer file is deleted — see _is_consumed for the proof.
                if self._is_consumed(file.span.end_seq, file.modified, floor, proof_time):
                    await s3._rm(key)
                    continue

                try:
                    async with await s3.open_async(key, "rb") as f:
                        data = await f.read()
                        table = pq.read_table(pa.BufferReader(data))
                except FileNotFoundError:
                    # A concurrent run, or a retry of this activity, can have deleted the file
                    # between the listing and this open — the listing is a snapshot, not a lease.
                    await self._logger.adebug("cdc_buffer_file_already_consumed", key=key)
                    continue

                if applied_rows and applied_position is not None:
                    table, skipped = self._drop_applied_prefix(table, applied_position, applied_rows)
                    applied_rows -= skipped

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
