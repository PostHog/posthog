import asyncio

from django.conf import settings

import pyarrow as pa
import pyarrow.fs as pa_fs
from pyarrow.parquet import write_table
from structlog.types import FilteringBoundLogger

from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client, ensure_bucket_exists
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    person_property_projection_for,
)


class PersonPropertyRowSink:
    """Stages a projection of each synced chunk to S3 for the person-property upsert job.

    Mirrors ``CDPProducer``: gated on a hook so a table with no person-target source stages
    nothing, and only the columns the sources actually need (key + mapped columns) leave the
    pipeline. A post-sync job (later PR) reads these files and upserts person properties, then
    clears them.
    """

    def __init__(self, team_id: int, schema_id: str, job_id: str, logger: FilteringBoundLogger) -> None:
        self.team_id = team_id
        self.schema_id = schema_id
        self.job_id = job_id
        self.logger = logger
        self._projection: list[str] | None = None
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

    def _get_path_prefix(self) -> str:
        return f"{settings.DATAWAREHOUSE_BUCKET}/person_property_sync/{self.team_id}/{self.schema_id}/{self.job_id}"

    async def _get_projection(self) -> list[str] | None:
        """Columns to stage (union of key + mapped columns across the schema's enabled person
        sources), or None when nothing needs staging. Resolved once per run."""
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
        # Intersect with the table's real columns: a misconfigured source column just isn't staged
        # (the downstream job tolerates missing columns) rather than failing the sync.
        columns = [column for column in projection if column in table.column_names]
        if not columns:
            return
        projected = table.select(columns)
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
        """Drop any files left by a prior failed run so a re-run doesn't double-stage."""
        async with aget_s3_client() as s3_client:
            try:
                await s3_client._rm(f"s3://{self._get_path_prefix()}/", recursive=True)
            except FileNotFoundError:
                pass
