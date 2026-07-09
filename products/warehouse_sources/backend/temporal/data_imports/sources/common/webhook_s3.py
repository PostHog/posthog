from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Callable
from typing import Optional, TypeVar

from django.conf import settings
from django.db import OperationalError, close_old_connections

import orjson
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list

T = TypeVar("T")

_MAX_DB_READ_ATTEMPTS = 4


def _db_read_with_retry(fn: Callable[[], T]) -> T:
    """Run an idempotent main-DB read, retrying a transient connection failure with backoff.

    Temporal activities run in a long-lived worker that never goes through Django's request
    cycle, so a pooled Postgres connection can be closed server-side while it sits idle, or the
    connection pooler can reject the query with a wait timeout when the pool is saturated. Both
    surface as a transient ``OperationalError`` and both clear once a healthy connection is used.
    ``close_old_connections()`` evicts connections already known to be stale (and, after a failed
    query marks one unusable, drops it), so each attempt runs on a fresh connection; the short
    backoff also gives a saturated pool time to drain rather than retrying straight back into the
    same wait timeout. Must run inside the ``database_sync_to_async_pool`` thread so the eviction
    targets the same connection the query uses. ``DoesNotExist`` and other errors propagate.
    """
    attempt = 0
    while True:
        close_old_connections()
        try:
            return fn()
        except OperationalError:
            attempt += 1
            if attempt >= _MAX_DB_READ_ATTEMPTS:
                raise
            time.sleep(min(2 * attempt, 30))


class WebhookSourceManager:
    _inputs: SourceInputs
    _logger: FilteringBoundLogger

    def __init__(self, inputs: SourceInputs, logger: FilteringBoundLogger) -> None:
        self._inputs = inputs
        self._logger = logger

    def _get_webhook_s3_prefix(self) -> str:
        return f"s3://{settings.DATAWAREHOUSE_BUCKET}/source_webhook_producer/{self._inputs.team_id}/{self._inputs.schema_id}"

    def _strip_s3_protocol(self, s3_path: str) -> str:
        return s3_path.replace("s3://", "")

    async def webhook_enabled(self, skip_initial_sync_complete_check: bool = False) -> bool:
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        schema = await database_sync_to_async_pool(_db_read_with_retry)(
            lambda: ExternalDataSchema.objects.get(id=self._inputs.schema_id, team_id=self._inputs.team_id)
        )

        if (
            not schema.is_webhook
            or (skip_initial_sync_complete_check is not True and not schema.initial_sync_complete)
            or self._inputs.reset_pipeline
        ):
            await self._logger.adebug(
                f"webhook_enabled=False. schema.is_webhook={schema.is_webhook}. schema.initial_sync_complete={schema.initial_sync_complete}. self._inputs.reset_pipeline={self._inputs.reset_pipeline}"
            )
            return False

        has_webhook_function = await database_sync_to_async_pool(_db_read_with_retry)(
            lambda: HogFunction.objects.filter(
                inputs__source_id__value=self._inputs.source_id,
                team_id=self._inputs.team_id,
                type="warehouse_source_webhook",
                enabled=True,
                deleted=False,
            ).exists()
        )

        return has_webhook_function

    async def _list_webhook_parquet_files(self) -> list[str]:
        prefix = self._get_webhook_s3_prefix()

        async with aget_s3_client() as s3:
            try:
                ls_res = await s3._ls(prefix, detail=True)
                ls_values = ls_res.values() if isinstance(ls_res, dict) else ls_res
                entries = [f for f in ls_values if f["type"] != "directory" and f["Key"].endswith(".parquet")]
                # Read oldest-first (by S3 mtime, Key as a stable tiebreak) so a key's events reach
                # the loader in arrival order. The leading `is None` flag sends entries without a
                # LastModified to the end without ever comparing None to a timestamp.
                entries.sort(key=lambda f: (f.get("LastModified") is None, f.get("LastModified"), f["Key"]))
                files = [f"s3://{f['Key']}" for f in entries]

                await self._logger.adebug("list_webhook_parquet_files", prefix=prefix, file_count=len(files))

                return files
            except FileNotFoundError:
                await self._logger.adebug("webhook_folder_not_found", prefix=prefix)
                return []

    async def get_items(
        self,
        table_transformer: Optional[Callable[[pa.Table], pa.Table]] = None,
        batch_row_limit: int = 5000,
        batch_byte_limit: int = 200 * 1024 * 1024,
    ) -> AsyncGenerator[pa.Table]:
        files = await self._list_webhook_parquet_files()

        await self._logger.adebug(f"Webhook source reading {len(files)} files")

        def finalize_batch(tables: list[pa.Table]) -> pa.Table:
            # Dedupe across the whole concatenated batch, not per file: a yielded batch can span
            # several S3 files, and the same id (e.g. a run's queued/completed events) can land in
            # different files. A per-file pass would let both survive into one batch.
            merged = pa.concat_tables(tables, promote_options="permissive")
            return table_transformer(merged) if table_transformer else merged

        batch_tables: list[pa.Table] = []
        batch_paths: list[str] = []
        batch_rows = 0
        batch_bytes = 0

        async with aget_s3_client() as s3:
            for file in files:
                path = self._strip_s3_protocol(file)

                await self._logger.adebug(f"Webhook source reading file {path}")
                async with await s3.open_async(path, "rb") as f:
                    data = await f.read()
                    table = pq.read_table(pa.BufferReader(data))

                table = await self._validate_webhook_table(table)
                if table.num_rows == 0:
                    await self._logger.adebug("webhook_file_has_no_valid_rows", path=path)
                    await s3._rm(path)
                    continue

                table = self._transform_webhook_table(table)

                batch_tables.append(table)
                batch_paths.append(path)
                batch_rows += table.num_rows
                batch_bytes += table.nbytes

                if batch_rows >= batch_row_limit or batch_bytes >= batch_byte_limit:
                    merged = finalize_batch(batch_tables)
                    await self._logger.adebug(
                        "webhook_batch_yield",
                        file_count=len(batch_paths),
                        row_count=merged.num_rows,
                        byte_count=merged.nbytes,
                    )

                    yield merged

                    for p in batch_paths:
                        await s3._rm(p)
                    batch_tables = []
                    batch_paths = []
                    batch_rows = 0
                    batch_bytes = 0

            # Yield any remaining rows
            if batch_tables:
                merged = finalize_batch(batch_tables)
                await self._logger.adebug(
                    "webhook_batch_yield",
                    file_count=len(batch_paths),
                    row_count=merged.num_rows,
                    byte_count=merged.nbytes,
                )

                yield merged

                for p in batch_paths:
                    await s3._rm(p)

    async def _validate_webhook_table(self, table: pa.Table) -> pa.Table:
        expected_team_id = self._inputs.team_id
        expected_schema_id = str(self._inputs.schema_id)

        team_id_match = pc.equal(table.column("team_id"), expected_team_id)
        schema_id_match = pc.equal(table.column("schema_id"), expected_schema_id)
        valid_mask = pc.and_(team_id_match, schema_id_match)

        filtered = table.filter(valid_mask)
        dropped = table.num_rows - filtered.num_rows
        if dropped > 0:
            await self._logger.adebug(
                "webhook_rows_filtered",
                dropped=dropped,
                expected_team_id=expected_team_id,
                expected_schema_id=expected_schema_id,
            )

        return filtered

    def _transform_webhook_table(self, table: pa.Table) -> pa.Table:
        rows = [orjson.loads(str(s)) for s in table.column("payload_json").to_pylist()]
        return table_from_py_list(rows)
