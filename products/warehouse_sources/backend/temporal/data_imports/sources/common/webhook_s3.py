from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Optional

from django.conf import settings

import orjson
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from structlog.types import FilteringBoundLogger

from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.batching import (
    DEFAULT_BATCH_BYTE_LIMIT,
    DEFAULT_BATCH_ROW_LIMIT,
    TableBatcher,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.db import db_read_with_retry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs


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

    async def webhook_enabled(self, webhook_only: bool = False) -> bool:
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        schema = await database_sync_to_async_pool(db_read_with_retry)(
            lambda: ExternalDataSchema.objects.get(id=self._inputs.schema_id, team_id=self._inputs.team_id)
        )

        # A webhook-first resource's poll does no backfill, so the poll can neither seed the
        # table (skip the initial-sync gate) nor rebuild it after a reset (ignore reset_pipeline
        # — honoring it would force the poll path and orphan rows only webhooks can provide).
        if (
            not schema.is_webhook
            or (not webhook_only and not schema.initial_sync_complete)
            or (not webhook_only and self._inputs.reset_pipeline)
        ):
            await self._logger.adebug(
                f"webhook_enabled=False. schema.is_webhook={schema.is_webhook}. "
                f"schema.initial_sync_complete={schema.initial_sync_complete}. "
                f"webhook_only={webhook_only}. reset_pipeline={self._inputs.reset_pipeline}"
            )
            return False

        has_webhook_function = await database_sync_to_async_pool(db_read_with_retry)(
            lambda: HogFunction.objects.filter(
                inputs__source_id__value=self._inputs.source_id,
                team_id=self._inputs.team_id,
                type="warehouse_source_webhook",
                enabled=True,
                deleted=False,
            ).exists()
        )

        return has_webhook_function

    async def schema_is_webhook(self) -> bool:
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        schema = await database_sync_to_async_pool(db_read_with_retry)(
            lambda: ExternalDataSchema.objects.get(id=self._inputs.schema_id, team_id=self._inputs.team_id)
        )
        return bool(schema.is_webhook)

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
        batch_row_limit: int = DEFAULT_BATCH_ROW_LIMIT,
        batch_byte_limit: int = DEFAULT_BATCH_BYTE_LIMIT,
    ) -> AsyncGenerator[pa.Table]:
        files = await self._list_webhook_parquet_files()

        await self._logger.adebug(f"Webhook source reading {len(files)} files")

        def finalize_batch(tables: list[pa.Table]) -> pa.Table:
            # Concatenate the whole batch, not per file: a yielded batch can span several S3 files,
            # and the same id (e.g. a run's queued/completed events) can land in different files, so
            # the downstream transformer must see all of them together to dedupe across the batch.
            try:
                merged = pa.concat_tables(tables, promote_options="permissive")
            except (pa.ArrowTypeError, pa.ArrowInvalid):
                # Each file's table is typed independently, so one payload field can infer as
                # different, non-promotable types across files (e.g. a number that arrives quoted in
                # one delivery and bare in another — string vs int64), which concat can't reconcile.
                # Rebuild through the shared row-to-table path, which resolves a column's mixed types
                # the same way a single multi-typed file already does.
                rows = [row for table in tables for row in table.to_pylist()]
                merged = table_from_py_list(rows)
            return table_transformer(merged) if table_transformer else merged

        batch: TableBatcher[str] = TableBatcher(row_limit=batch_row_limit, byte_limit=batch_byte_limit)

        async with aget_s3_client() as s3:
            for file in files:
                path = self._strip_s3_protocol(file)

                await self._logger.adebug(f"Webhook source reading file {path}")
                try:
                    async with await s3.open_async(path, "rb") as f:
                        data = await f.read()
                        table = pq.read_table(pa.BufferReader(data))
                except FileNotFoundError:
                    # A concurrent run (or a retry of this same activity) can have already
                    # read and deleted this file between our listing and this open, since
                    # this is a plain listing snapshot, not a lease on the listed files.
                    await self._logger.adebug("webhook_file_already_consumed", path=path)
                    continue

                table = await self._validate_webhook_table(table)
                if table.num_rows == 0:
                    await self._logger.adebug("webhook_file_has_no_valid_rows", path=path)
                    await s3._rm(path)
                    continue

                table = self._transform_webhook_table(table)

                if batch.add(table, path):
                    merged = finalize_batch(batch.tables)
                    await self._logger.adebug(
                        "webhook_batch_yield",
                        file_count=len(batch.items),
                        row_count=merged.num_rows,
                        byte_count=merged.nbytes,
                    )

                    yield merged

                    for p in batch.items:
                        await s3._rm(p)
                    batch.reset()

            # Yield any remaining rows
            if batch:
                merged = finalize_batch(batch.tables)
                await self._logger.adebug(
                    "webhook_batch_yield",
                    file_count=len(batch.items),
                    row_count=merged.num_rows,
                    byte_count=merged.nbytes,
                )

                yield merged

                for p in batch.items:
                    await s3._rm(p)

    async def _validate_webhook_table(self, table: pa.Table) -> pa.Table:
        expected_team_id = self._inputs.team_id
        expected_schema_id = str(self._inputs.schema_id)

        team_id_match = pc.equal(table.column("team_id"), pa.scalar(expected_team_id))
        schema_id_match = pc.equal(table.column("schema_id"), pa.scalar(expected_schema_id))
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
