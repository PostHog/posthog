import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import pyarrow as pa
import deltalake
import pyarrow.fs as pa_fs
import deltalake.exceptions
from pyarrow.parquet import ParquetFile, write_table
from structlog.types import FilteringBoundLogger

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.utils import aretry_on_db_connection_drop

from products.data_warehouse.backend.facade.api import aget_s3_client, ensure_bucket_exists
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    AccountPropertySourceProjection,
    WarehouseBinding,
    account_property_projection_for,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.account_property_paths import (
    binding_staged_prefix,
    job_staged_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import delta_storage_options

# A sibling job prefix whose newest file is older than this is considered abandoned (its consumer
# never ran, or gave up retrying) and is swept. Anything younger may belong to a consumer that is
# merely lagging behind the sync schedule and must survive — deleting it would silently drop that
# sync's staged delta, which an incremental sync never re-stages until the rows change again.
ABANDONED_STAGED_PREFIX_TTL = timedelta(days=7)
_PARQUET_BATCH_SIZE = 50_000

# Two distinct message shapes pyarrow's S3FileSystem can raise as a bare OSError for the same
# missing-key condition, depending on which call hit it: a direct GetObject (the raw AWS text) vs.
# `open_input_file`'s own preflight `GetFileInfo` check, which formats a fixed, backend-agnostic
# "not found" message instead of surfacing the AWS error. `_stage_committed_files` only ever calls
# `open_input_file` (random-access reads), so only the second shape is reachable from here in
# practice — matched the same way as the equivalent NoSuchKey race in
# workflow_activities/repartition_table.py.
_MISSING_OBJECT_ERROR_NEEDLES = (
    "the specified key does not exist",
    "path does not exist",
)

# delta-rs raises this DeltaError, instead of the OSError above, when the pinned version wasn't
# vacuumed but the whole table was reset and recommitted from scratch by a later materialize run
# (data-modeling's reset_table/full_refresh purges the table's _delta_log along with its data) — the
# log the reader replays now ends at the fresh table's latest commit, which is lower than the version
# pinned before the reset. Same queued-for-hours race as the vacuum case above, different delta-rs
# entry point.
_LOG_SEGMENT_VERSION_MISMATCH_NEEDLE = "not the same as the specified end version"


def _is_missing_object_error(error: BaseException) -> bool:
    if not isinstance(error, OSError):
        return False
    message = str(error).lower()
    return any(needle in message for needle in _MISSING_OBJECT_ERROR_NEEDLES)


def _is_stale_pinned_version_error(error: BaseException) -> bool:
    if _is_missing_object_error(error):
        return True
    return isinstance(error, deltalake.exceptions.DeltaError) and _LOG_SEGMENT_VERSION_MISMATCH_NEEDLE in str(error)


class AccountPropertyRowSink:
    """Projects a committed materialized-view Delta snapshot into job-scoped Parquet files."""

    def __init__(
        self,
        team_id: int,
        binding: WarehouseBinding,
        job_id: str,
        logger: FilteringBoundLogger,
    ) -> None:
        self.team_id = team_id
        self.binding = binding
        self.job_id = job_id
        self.logger = logger
        self._projection: list[AccountPropertySourceProjection] | None = None
        self._projection_resolved = False
        self._fs_cache: pa_fs.S3FileSystem | None = None

    def _get_fs(self) -> pa_fs.S3FileSystem:
        # Cached per instance: stage_chunk() calls this once per chunk, and a sink lives for a
        # whole sync (potentially thousands of chunks). A fresh S3FileSystem per call opens its
        # own AWS SDK client/connections that outlive the call, exhausting the process' file
        # descriptor limit over a long sync.
        if self._fs_cache is not None:
            return self._fs_cache

        if settings.USE_LOCAL_SETUP:
            ensure_bucket_exists(
                f"s3://{self._get_path_prefix()}",
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )
            self._fs_cache = pa_fs.S3FileSystem(
                access_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                secret_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
            )
        else:
            self._fs_cache = pa_fs.S3FileSystem(region=settings.DATA_WAREHOUSE_S3_REGION)

        return self._fs_cache

    def _get_binding_prefix(self) -> str:
        return binding_staged_prefix(self.team_id, self.binding)

    def _get_path_prefix(self) -> str:
        return job_staged_prefix(self.team_id, self.binding, self.job_id)

    async def _get_projection(self) -> list[AccountPropertySourceProjection] | None:
        """One projection per enabled account source on the binding (key + mapped columns), or None
        when nothing needs staging. Resolved once per run.

        The resolver reads the app DB (team scoping, enabled profile sources), so a long-lived
        worker's pooled connection can have gone stale (pooler recycle, failover, deploy) since it
        was last used. Retry once on a fresh connection rather than let that escape as
        error-tracking noise, or as a silently skipped account-property sync for the run.
        """
        if not self._projection_resolved:
            self._projection = await aretry_on_db_connection_drop(
                lambda: database_sync_to_async_pool(account_property_projection_for)(self.team_id, self.binding)
            )
            self._projection_resolved = True
        return self._projection

    async def should_run(self) -> bool:
        return bool(await self._get_projection())

    async def stage_chunk(self, chunk: int, table: pa.Table) -> None:
        projection = await self._get_projection()
        if not projection:
            return
        table_columns = set(table.column_names)
        # Stage a source only when its key (account external identifier) column is present, so a staged file
        # never carries property values with no identifier to attach them to. A missing key column
        # skips that source rather than failing the sync (e.g. after upstream schema drift).
        columns: set[str] = set()
        for source in projection:
            if source.key_column not in table_columns:
                continue
            columns.update(column for column in source.columns if column in table_columns)
        if not columns:
            return
        projected = table.select(sorted(columns))
        await self.logger.adebug(
            f"Staging account-property chunk {chunk} ({len(columns)} cols) to {self._get_path_prefix()}"
        )
        await asyncio.to_thread(
            write_table,
            projected,
            f"{self._get_path_prefix()}/chunk_{chunk:06d}.parquet",
            filesystem=self._get_fs(),
            compression="zstd",
            use_dictionary=True,
        )

    async def stage_delta_snapshot(self, table_uri: str, delta_version: int) -> bool:
        projection = await self._get_projection()
        if not projection:
            return False

        await self.clear()
        try:
            await self._stage_committed_files(table_uri, delta_version)
        except (OSError, deltalake.exceptions.DeltaError) as error:
            if not _is_stale_pinned_version_error(error):
                raise
            # `delta_version` was pinned right after the materialize run that produced it, but the
            # staging child workflow that calls this can sit queued for hours before it actually
            # runs. If the same view gets materialized again in the meantime, that run's vacuum
            # (DELTA_TABLE_RETENTION_HOURS) can reclaim the pinned version's files before we read
            # them, or a full refresh can reset the table and recommit it from scratch, leaving the
            # pinned version behind entirely. Re-stage from whatever is committed now instead: vacuum
            # never removes a file the current version still references, and a freshly reset table's
            # latest version is by definition still there, so this snapshot can't be pulled out from
            # under us the same way.
            await self.logger.awarning(
                f"Delta version {delta_version} was vacuumed or superseded before staging read it; "
                "re-staging the current committed snapshot instead"
            )
            await self.clear()
            await self._stage_committed_files(table_uri, delta_version=None)
        return True

    async def _stage_committed_files(self, table_uri: str, delta_version: int | None) -> None:
        delta_table = await asyncio.to_thread(
            deltalake.DeltaTable,
            table_uri,
            version=delta_version,
            storage_options=delta_storage_options(),
        )
        chunk = 0
        for file_uri in sorted(delta_table.file_uris()):
            input_file = await asyncio.to_thread(self._get_fs().open_input_file, file_uri.removeprefix("s3://"))
            try:
                parquet_file = await asyncio.to_thread(ParquetFile, input_file)
                batches = await asyncio.to_thread(parquet_file.iter_batches, batch_size=_PARQUET_BATCH_SIZE)
                while (batch := await asyncio.to_thread(next, batches, None)) is not None:
                    await self.stage_chunk(chunk, pa.Table.from_batches([batch]))
                    chunk += 1
            finally:
                await asyncio.to_thread(input_file.close)

    async def clear(self) -> None:
        """Drop this job's prior attempt and sweep abandoned sibling jobs."""
        async with aget_s3_client() as s3_client:
            own_prefix_error: Exception | None = None
            try:
                await s3_client._rm(f"s3://{self._get_path_prefix()}/", recursive=True)
            except FileNotFoundError:
                pass
            except Exception as e:
                own_prefix_error = e
            await self._sweep_abandoned_sibling_prefixes(s3_client)
            if own_prefix_error is not None:
                raise own_prefix_error

    async def _sweep_abandoned_sibling_prefixes(self, s3_client: Any) -> None:
        try:
            entries = await s3_client._find(f"s3://{self._get_binding_prefix()}/", detail=True)
        except FileNotFoundError:
            return
        if not isinstance(entries, dict) or not entries:
            return

        binding_prefix = self._get_binding_prefix().lstrip("/")
        files_by_job: dict[str, list[str]] = {}
        newest_by_job: dict[str, datetime] = {}
        for path, info in entries.items():
            key = path.lstrip("/")
            relative = key[len(binding_prefix) :].lstrip("/")
            job_segment = relative.split("/", 1)[0]
            if not job_segment or job_segment == str(self.job_id):
                continue
            files_by_job.setdefault(job_segment, []).append(key)
            last_modified = info.get("LastModified") if isinstance(info, dict) else None
            if last_modified is not None:
                current = newest_by_job.get(job_segment)
                if current is None or last_modified > current:
                    newest_by_job[job_segment] = last_modified

        cutoff = datetime.now(UTC) - ABANDONED_STAGED_PREFIX_TTL
        stale_files = [
            key
            for job_segment, keys in files_by_job.items()
            # A prefix with no LastModified at all holds only directory markers — safe to sweep.
            if (newest := newest_by_job.get(job_segment)) is None or newest < cutoff
            for key in keys
        ]
        if not stale_files:
            return
        await self.logger.adebug(
            f"Sweeping {len(stale_files)} abandoned account-property staged files under {binding_prefix}"
        )
        await s3_client._rm([f"s3://{key}" for key in stale_files])
