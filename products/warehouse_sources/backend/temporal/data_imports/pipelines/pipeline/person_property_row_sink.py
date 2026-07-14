import asyncio

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


class PersonPropertyRowSink:
    """Stages a projection of each synced chunk to S3 for the person-property upsert job.

    Mirrors ``CDPProducer``: gated on a hook so a table with no person-target source stages
    nothing, and only the columns the sources actually need (key + mapped columns) leave the
    pipeline. A source is staged only when its key (person identifier) column is present in the
    synced chunk, so a staged file always carries an identifier to attach its properties to. A
    post-sync job (later PR) reads these files and upserts person properties, then clears them.
    """

    def __init__(self, team_id: int, schema_id: str, job_id: str, logger: FilteringBoundLogger) -> None:
        self.team_id = team_id
        self.schema_id = schema_id
        self.job_id = job_id
        self.logger = logger
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
            f"{self._get_path_prefix()}/chunk_{chunk}.parquet",
            filesystem=self._get_fs(),
            compression="zstd",
            use_dictionary=True,
        )

    async def clear_chunks(self) -> None:
        """Drop staged files left under this schema's prefix before a run stages fresh ones.

        Cleared at the schema level (not just this job) so files from a prior job that was never
        consumed by the downstream upsert job cannot accumulate across repeated syncs; it also
        stops a retry of the same job from double-staging. The downstream job clears the files it
        consumes on success; this is the backstop for abandoned prefixes.
        """
        async with aget_s3_client() as s3_client:
            try:
                await s3_client._rm(f"s3://{self._get_schema_prefix()}/", recursive=True)
            except FileNotFoundError:
                pass
