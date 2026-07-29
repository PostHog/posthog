import time
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

import pyarrow as pa
import pyarrow.fs as pa_fs
from pyarrow.parquet import write_table
from structlog.types import FilteringBoundLogger

from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client, ensure_bucket_exists
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySourceProjection,
    person_property_projection_for,
)

# A sibling job prefix whose newest file is older than this is considered abandoned (its consumer
# never ran, or gave up retrying) and is swept. Anything younger may belong to a consumer that is
# merely lagging behind the sync schedule and must survive — deleting it would silently drop that
# sync's staged delta, which an incremental sync never re-stages until the rows change again.
ABANDONED_STAGED_PREFIX_TTL = timedelta(days=7)


class PersonPropertyRowSink:
    """Stages a projection of each synced chunk to S3 for the person-property upsert job.

    Mirrors ``CDPProducer``: gated on a hook so a table with no person-target source stages
    nothing, and only the columns the sources actually need (key + mapped columns) leave the
    pipeline. A source is staged only when its key (person identifier) column is present in the
    synced chunk, so a staged file always carries an identifier to attach its properties to. A
    post-sync job (later PR) reads these files and upserts person properties, then clears them.

    Multiple job prefixes can coexist under a schema while the consumer lags, so the consumer
    must apply prefixes in job order (or last-write-wins per person key) — a lagged older job
    applied after a newer one would regress properties to stale values. Within one job, staged
    files from a retried attempt sort after the failed attempt's (attempt-timestamped names), so
    per-person last-write-wins inside the job holds too.
    """

    def __init__(
        self, team_id: int, schema_id: str, job_id: str, logger: FilteringBoundLogger, *, is_incremental: bool
    ) -> None:
        self.team_id = team_id
        self.schema_id = schema_id
        self.job_id = job_id
        self.logger = logger
        self._is_incremental = is_incremental
        # Per-attempt token baked into staged filenames. An incremental retry resumes past the
        # already-committed cursor, so its chunk indices restart at 0 while the earlier attempt's
        # rows are never re-extracted — reusing plain `chunk_{n}` names would overwrite (and lose)
        # them. Seconds-since-epoch keeps names lexicographically ordered across attempts.
        self._attempt_token = str(int(time.time()))
        self._projection: list[PersonPropertySourceProjection] | None = None
        self._projection_resolved = False

    def _get_fs(self) -> pa_fs.S3FileSystem:
        if settings.USE_LOCAL_SETUP:
            ensure_bucket_exists(
                f"s3://{self._get_path_prefix()}",
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )
            return pa_fs.S3FileSystem(
                access_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                secret_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
            )

        return pa_fs.S3FileSystem()

    def _get_schema_prefix(self) -> str:
        return f"{settings.DATAWAREHOUSE_BUCKET}/person_property_sync/{self.team_id}/{self.schema_id}"

    def _get_path_prefix(self) -> str:
        return f"{self._get_schema_prefix()}/{self.job_id}"

    async def _get_projection(self) -> list[PersonPropertySourceProjection] | None:
        """One projection per enabled person source on the schema (key + mapped columns), or None
        when nothing needs staging. Resolved once per run."""
        if not self._projection_resolved:
            self._projection = await database_sync_to_async_pool(person_property_projection_for)(
                self.team_id, self.schema_id
            )
            self._projection_resolved = True
        return self._projection

    async def should_stage(self) -> bool:
        return bool(await self._get_projection())

    async def stage_chunk(self, chunk: int, table: pa.Table) -> None:
        projection = await self._get_projection()
        if not projection:
            return
        table_columns = set(table.column_names)
        # Stage a source only when its key (person identifier) column is present, so a staged file
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
            f"Staging person-property chunk {chunk} ({len(columns)} cols) to {self._get_path_prefix()}"
        )
        await asyncio.to_thread(
            write_table,
            projected,
            f"{self._get_path_prefix()}/chunk_{self._attempt_token}_{chunk:06d}.parquet",
            filesystem=self._get_fs(),
            compression="zstd",
            use_dictionary=True,
        )

    async def clear_chunks(self) -> None:
        """Drop this job's own staged files (full refresh only), plus sibling job prefixes
        abandoned long enough.

        Own-prefix clearing stops a retried job from leaving stale files behind, but it is only
        safe when the retry re-extracts everything — i.e. a full refresh. An incremental retry
        resumes past the cursor the failed attempt already committed, so its earlier staged files
        are that data's only record and must survive; duplicates a full re-window would produce
        are deduped downstream anyway (snapshot diff + last-write-wins).

        Sibling prefixes are NOT cleared wholesale: the downstream upsert job deletes them as it
        consumes them, and a recent sibling may simply belong to a consumer that is lagging —
        wiping it would lose that sync's delta. Only prefixes older than
        ``ABANDONED_STAGED_PREFIX_TTL`` are swept, as the backstop against a consumer that never
        ran.
        """
        async with aget_s3_client() as s3_client:
            if not self._is_incremental:
                try:
                    await s3_client._rm(f"s3://{self._get_path_prefix()}/", recursive=True)
                except FileNotFoundError:
                    pass
            await self._sweep_abandoned_sibling_prefixes(s3_client)

    async def _sweep_abandoned_sibling_prefixes(self, s3_client: Any) -> None:
        try:
            entries = await s3_client._find(f"s3://{self._get_schema_prefix()}/", detail=True)
        except FileNotFoundError:
            return
        if not isinstance(entries, dict) or not entries:
            return

        schema_prefix = self._get_schema_prefix().lstrip("/")
        files_by_job: dict[str, list[str]] = {}
        newest_by_job: dict[str, datetime] = {}
        for path, info in entries.items():
            key = path.lstrip("/")
            relative = key[len(schema_prefix) :].lstrip("/")
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
            f"Sweeping {len(stale_files)} abandoned person-property staged files under {schema_prefix}"
        )
        await s3_client._rm([f"s3://{key}" for key in stale_files])
