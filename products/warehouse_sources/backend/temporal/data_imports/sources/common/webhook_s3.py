from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from enum import StrEnum
from typing import Any, Optional

from django.conf import settings
from django.db import transaction

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

# Informational key on a job's `schema_snapshot`. The job keeps `sync_type: webhook`, because the next
# run compares it with the schema's sync type to decide whether it may continue this job's cursor.
WEBHOOK_FALLBACK_SNAPSHOT_KEY = "webhook_fallback"


class WebhookState(StrEnum):
    # Read the rows that the webhook delivered.
    ACTIVE = "active"
    # The run polls the API by design: the table is not on webhook sync, or the run seeds or rebuilds it.
    POLL = "poll"
    # The table is on webhook sync, but the source has no enabled webhook, so nothing delivers rows.
    NO_WEBHOOK = "no_webhook"


class WebhookFallback(StrEnum):
    """How a webhook-sync run with no enabled webhook polls the API instead."""

    FULL_REFRESH = "full_refresh"
    INCREMENTAL = "incremental"


def _stamp_webhook_fallback(job_id: str, team_id: int, fallback: WebhookFallback) -> None:
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    with transaction.atomic():
        job = (
            ExternalDataJob.objects.select_for_update()
            .filter(id=job_id, team_id=team_id)
            .only("id", "schema_snapshot")
            .first()
        )
        if job is None:
            return
        snapshot = {**dict(job.schema_snapshot or {}), WEBHOOK_FALLBACK_SNAPSHOT_KEY: fallback.value}
        ExternalDataJob.objects.filter(id=job.id, team_id=team_id).update(schema_snapshot=snapshot)


def _webhook_folder(team_id: int, schema_id: str) -> str:
    return f"{settings.DATAWAREHOUSE_BUCKET}/source_webhook_producer/{team_id}/{schema_id}"


def _consumed_manifest_folder(team_id: int, schema_id: str) -> str:
    # A subfolder, so the non-recursive `.parquet` listing of the webhook folder never reads a manifest.
    return f"{_webhook_folder(team_id, schema_id)}/_consumed"


def _attempt_manifest_folder(team_id: int, schema_id: str, job_id: str, attempt: int) -> str:
    # One folder for each attempt, because two attempts of one job can run at the same time and
    # list different files. The attempt that completes the job must delete only the files it queued.
    return f"{_consumed_manifest_folder(team_id, schema_id)}/{job_id}-a{attempt}"


async def delete_consumed_webhook_files(team_id: int, schema_id: str, job_id: str, attempt: int) -> int:
    """Delete the webhook files that one completed attempt of a job loaded, and then all manifests.

    Call this only after the attempt completed the job. Until then, the files are the only copy of
    their events, so a run that fails keeps them and the next run reads them again.

    Also deletes the manifests of other jobs and attempts. A manifest of a failed job is never used
    again. If an attempt that still runs loses its manifest, it deletes nothing when it completes.
    Its files then stay for the next run, which reads them again. Webhook tables merge on the
    primary key, so the second read changes no rows.

    Returns the number of files deleted, or 0 when the attempt has no manifest.
    """
    attempt_folder = _attempt_manifest_folder(team_id, schema_id, job_id, attempt)
    async with aget_s3_client() as s3:
        try:
            # `refresh`, because the cached listing of this client can predate the parts that the
            # extraction worker wrote.
            parts = await s3._ls(attempt_folder, detail=False, refresh=True)
        except FileNotFoundError:
            return 0

        files: list[str] = []
        for part in parts:
            async with await s3.open_async(part, "rb") as f:
                files.extend(orjson.loads(await f.read())["files"])

        if files:
            # A list of literal keys goes to bulk deletes, which ignore a key that is already gone.
            await s3._rm(files)
        try:
            await s3._rm(_consumed_manifest_folder(team_id, schema_id), recursive=True)
        except FileNotFoundError:
            pass
    return len(files)


class WebhookSourceManager:
    _inputs: SourceInputs
    _logger: FilteringBoundLogger
    _state: WebhookState | None

    def __init__(self, inputs: SourceInputs, logger: FilteringBoundLogger) -> None:
        self._inputs = inputs
        self._logger = logger
        self._state = None

    def _get_webhook_s3_prefix(self) -> str:
        return f"s3://{_webhook_folder(self._inputs.team_id, self._inputs.schema_id)}"

    def _strip_s3_protocol(self, s3_path: str) -> str:
        return s3_path.replace("s3://", "")

    async def webhook_enabled(self, webhook_only: bool = False) -> bool:
        return await self.webhook_state(webhook_only=webhook_only) is WebhookState.ACTIVE

    async def webhook_state(self, webhook_only: bool = False) -> WebhookState:
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
        from products.warehouse_sources.backend.webhook_registration import source_has_enabled_webhook

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
            self._state = WebhookState.POLL
            return self._state

        has_webhook_function = await database_sync_to_async_pool(db_read_with_retry)(
            lambda: source_has_enabled_webhook(self._inputs.team_id, self._inputs.source_id)
        )

        self._state = WebhookState.ACTIVE if has_webhook_function else WebhookState.NO_WEBHOOK
        return self._state

    @property
    def webhook_missing(self) -> bool:
        """Whether the last `webhook_state` check found a webhook-sync table with no enabled webhook."""
        return self._state is WebhookState.NO_WEBHOOK

    async def record_webhook_fallback(self, fallback: WebhookFallback) -> None:
        """Mark this run's job as one that polls the API because the table has no enabled webhook.

        Call it after `webhook_enabled` returns False and the source starts to poll. It does nothing
        unless that check found a webhook-sync table with no enabled webhook, so an initial sync or a
        reset, which poll by design, stay unmarked. Without the mark, the job still reads as a webhook
        sync, so its rows count as webhook rows.
        """
        if not self.webhook_missing:
            return
        await self._logger.awarning(
            "This table uses webhook sync, but the source has no active webhook, so this sync reads the "
            "source API instead. Set up the webhook on the source's Webhook tab, or change the sync method.",
            webhook_fallback=fallback.value,
        )
        await database_sync_to_async_pool(_stamp_webhook_fallback)(self._inputs.job_id, self._inputs.team_id, fallback)

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
        # The files of a queued batch are not deleted here, because the batch can still fail to load,
        # and the files are then the only copy of its events. They are recorded in a manifest, and
        # the loader deletes them with `delete_consumed_webhook_files` when the job completes.
        batch_number = 0

        async with aget_s3_client() as s3:
            for file in files:
                path = self._strip_s3_protocol(file)

                await self._logger.adebug(f"Webhook source reading file {path}")
                try:
                    async with await s3.open_async(path, "rb") as f:
                        data = await f.read()
                        table = pq.read_table(pa.BufferReader(data))
                except FileNotFoundError:
                    # A concurrent job that read this file can complete and delete it between our
                    # listing and this open, since this is a plain listing snapshot, not a lease on
                    # the listed files. That job loaded the file's rows, so skipping it loses nothing.
                    await self._logger.adebug("webhook_file_already_consumed", path=path)
                    continue

                table = await self._validate_webhook_table(table)
                if table.num_rows == 0:
                    await self._logger.adebug("webhook_file_has_no_valid_rows", path=path)
                    await s3._rm(path)
                    continue

                table = self._transform_webhook_table(table)

                if batch.add(table, path):
                    merged = await asyncio.to_thread(finalize_batch, batch.tables)
                    await self._logger.adebug(
                        "webhook_batch_yield",
                        file_count=len(batch.items),
                        row_count=merged.num_rows,
                        byte_count=merged.nbytes,
                    )

                    yield merged

                    await self._record_consumed_files(s3, batch_number, batch.items)
                    batch_number += 1
                    batch.reset()

            # Yield any remaining rows
            if batch:
                merged = await asyncio.to_thread(finalize_batch, batch.tables)
                await self._logger.adebug(
                    "webhook_batch_yield",
                    file_count=len(batch.items),
                    row_count=merged.num_rows,
                    byte_count=merged.nbytes,
                )

                yield merged

                await self._record_consumed_files(s3, batch_number, batch.items)

    async def _record_consumed_files(self, s3: Any, batch_number: int, files: list[str]) -> None:
        # One part for each batch, written after the batch is queued, so a part never lists a file of
        # a batch that is not queued, and a large backlog does not rewrite the same list again.
        folder = _attempt_manifest_folder(
            self._inputs.team_id, self._inputs.schema_id, self._inputs.job_id, self._inputs.activity_attempt
        )
        await s3._pipe_file(f"{folder}/{batch_number:06d}.json", orjson.dumps({"files": files}))

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
