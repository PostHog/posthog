from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Callable
from datetime import timedelta
from typing import Optional, TypeVar

from django.conf import settings
from django.db import OperationalError, close_old_connections

import orjson
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async
from structlog.types import FilteringBoundLogger

from posthog.clickhouse.client import sync_execute
from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

# Statuses that indicate the webhook sender's request was rejected for a reason
# the user must fix (e.g. a bad signing secret). 5xx (our fault), 429 (hog-watcher
# disabled) and 404 (function deleted) are deliberately excluded — they are not
# user-actionable signing-secret problems and must not disable a schema.
_NON_RETRYABLE_WEBHOOK_STATUSES = {400, 401, 403}
# Number of consecutive recent failures required before we fail the run — guards
# against a single transient rejection.
_MIN_CONSECUTIVE_WEBHOOK_FAILURES = 3
# Leading phrase of the raised error. Must stay byte-equal to the key registered
# in `Any_Source_Errors` (substring match) so the run is classified non-retryable.
WEBHOOK_DELIVERY_FAILING_ERROR = "Webhook delivery is failing"

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

    async def _webhook_failure_lookback_seconds(self) -> int:
        """Window to look back for failures — one sync interval plus a buffer.

        The buffer covers run duration, scheduler delay and ClickHouse ingest lag.
        The schedule jitter we add is a one-time start-time offset, so inter-run
        spacing stays ~one interval; the buffer does not need to absorb it.
        """
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        schema = await database_sync_to_async_pool(ExternalDataSchema.objects.get)(
            id=self._inputs.schema_id, team_id=self._inputs.team_id
        )
        interval = schema.sync_frequency_interval or timedelta(hours=6)
        buffer = max(interval * 0.2, timedelta(minutes=5))
        return int((interval + buffer).total_seconds())

    async def _persistent_webhook_failure_reason(self) -> Optional[str]:
        """Return a reason string when recent deliveries are persistently failing
        with a non-retryable (auth/signature) status, else ``None``.

        A bad signing secret is rejected before per-event schema mapping, so those
        failures carry an empty ``schema_id`` (source-level). We match both this
        schema's rows and source-level rows.
        """
        window_seconds = await self._webhook_failure_lookback_seconds()
        rows = await sync_to_async(sync_execute)(
            """
            SELECT http_status, ok, reason
            FROM warehouse_webhook_delivery_status
            WHERE team_id = %(team_id)s
              AND source_id = %(source_id)s
              AND (schema_id = %(schema_id)s OR schema_id = '')
              AND timestamp > now() - toIntervalSecond(%(window_seconds)s)
            ORDER BY timestamp DESC
            LIMIT 50
            """,
            {
                "team_id": self._inputs.team_id,
                "source_id": str(self._inputs.source_id),
                "schema_id": str(self._inputs.schema_id),
                "window_seconds": window_seconds,
            },
        )
        return self._classify_webhook_failure(rows)

    @staticmethod
    def _classify_webhook_failure(rows: list[tuple]) -> Optional[str]:
        # Rows are newest-first. Count the leading run of non-retryable failures;
        # a success (recovery) or any other status (transient) breaks the run.
        consecutive = 0
        latest_reason: Optional[str] = None
        for http_status, ok, reason in rows:
            if ok == 1 or http_status not in _NON_RETRYABLE_WEBHOOK_STATUSES:
                break
            if latest_reason is None:
                latest_reason = reason or f"HTTP {http_status}"
            consecutive += 1

        if consecutive >= _MIN_CONSECUTIVE_WEBHOOK_FAILURES:
            return latest_reason
        return None

    async def _raise_on_persistent_webhook_failure(self) -> None:
        reason = await self._persistent_webhook_failure_reason()
        if reason is None:
            return

        await self._logger.awarning("webhook_delivery_persistently_failing", reason=reason)
        raise NonRetryableException(
            f"{WEBHOOK_DELIVERY_FAILING_ERROR}: {reason}. "
            "Check your webhook configuration (e.g. signing secret) in the source settings, "
            "then re-enable syncing."
        )

    async def get_items(
        self,
        table_transformer: Optional[Callable[[pa.Table], pa.Table]] = None,
        batch_row_limit: int = 5000,
        batch_byte_limit: int = 200 * 1024 * 1024,
    ) -> AsyncGenerator[pa.Table]:
        # Fail fast (non-retryably) if recent deliveries are persistently rejected
        # so the user is told to fix the webhook instead of silently importing 0 rows.
        await self._raise_on_persistent_webhook_failure()

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
