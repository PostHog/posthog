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
from typing import TYPE_CHECKING

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    BufferFileSpan,
    get_buffer_prefix,
    parse_buffer_file_name,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import read_load_position
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

# The only lane this manager serves. `cdc_only` and `both` need a second output per run, which one
# pipeline run cannot express — those schemas stay on the legacy extraction path.
CONSOLIDATED_TABLE_MODE = "consolidated"

# The loader's write mode for this lane, and the flag that tells the pipeline a run carries change
# events rather than rows read from a table.
CONSOLIDATED_WRITE_MODE = "incremental_merge"


# Slack when comparing an S3 mtime against a listing timestamp from our clock, so skew between the
# two can never make a file look older than a listing that in fact never saw it.
_CONSUMED_MTIME_MARGIN = dt.timedelta(minutes=5)

# The last buffer listing, `{"listed_at": iso, "job_id": str}` — a sibling of `cdc_load_position`.
# It matures into a deletion proof only if that job COMPLETES (see _completed_listing_time).
BUFFER_LISTING_CONFIG_KEY = "cdc_buffer_listing"


def serves_buffered_lane(schema: ExternalDataSchema) -> bool:
    """Schema-side conditions for buffered ingress; the source's `ingest_mode` is the other half.

    Fails closed on every axis: a lane this manager cannot write, or a schema with no table yet,
    stays on the legacy extraction path.
    """
    return bool(
        schema.is_cdc
        and schema.cdc_mode == "streaming"
        and schema.cdc_table_mode == CONSOLIDATED_TABLE_MODE
        and schema.initial_sync_complete
    )


def is_buffered_consolidated(schema: ExternalDataSchema, *, ingest_mode: str) -> bool:
    """Whether this schema's changes are delivered through the buffer."""
    return ingest_mode == "buffered" and serves_buffered_lane(schema)


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

    def __init__(self, inputs: SourceInputs, logger: FilteringBoundLogger) -> None:
        self._inputs = inputs
        self._logger = logger

    async def _read_consume_state(self, resource_name: str) -> tuple[int | None, dict | None]:
        """The lane's committed floor and the last listing stamp, read once per run.

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
        listing = (sync_type_config or {}).get(BUFFER_LISTING_CONFIG_KEY)
        return read_load_position(sync_type_config, resource_name), listing if isinstance(listing, dict) else None

    async def _stamp_listing(self, listed_at: dt.datetime) -> None:
        """Record that this run listed the buffer, before any file is read.

        The stamp becomes a deletion proof only once this run's job COMPLETES — see
        `_completed_listing_time`. Crashing after the stamp leaves the job un-completed, so a
        partial run can never prove anything.
        """
        from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys

        stamp = {"listed_at": listed_at.isoformat(), "job_id": str(self._inputs.job_id)}

        def _merge(config: dict) -> None:
            config[BUFFER_LISTING_CONFIG_KEY] = stamp

        await database_sync_to_async_pool(db_read_with_retry)(
            lambda: update_sync_type_config_keys(self._inputs.schema_id, self._inputs.team_id, mutate=_merge)
        )

    async def _completed_listing_time(self, listing: dict | None) -> dt.datetime | None:
        """When the buffer was last listed by a run that went on to COMPLETE, or None.

        Only a completed run proves consumption: completion means the generator drained every
        listed file and every staged batch committed. A job-status check on the stamped job is what
        keeps a no-op run (the legacy-backlog gate returns an empty response without listing) or a
        crashed run from ever serving as proof.
        """
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
        floor, prior_listing = await self._read_consume_state(resource_name)
        # Proof comes from the PRIOR stamp, resolved before this run overwrites it.
        proof_time = await self._completed_listing_time(prior_listing) if floor is not None else None
        await self._stamp_listing(listed_at)

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
