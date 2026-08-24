"""Delivering a run's batches to an S3-compatible bucket.

The simplest destination to make safe: each batch is written to a key derived from the run and
the batch index, so re-applying one overwrites its own object rather than appending a second
copy. Nothing here needs a staging area or a swap.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import ClassVar, Literal

import s3fs
import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async

from posthog.models.integration.aws import AWSS3Integration, S3CompatibleIntegration

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)

ParquetCompression = Literal["gzip", "bz2", "brotli", "lz4", "zstd", "snappy", "none"]
DEFAULT_COMPRESSION: ParquetCompression = "zstd"


class S3DestinationWriter:
    """Writes a run's batches as parquet objects under a prefix."""

    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._bucket = config.get("bucket") or ""
        self._prefix = (config.get("prefix") or "").strip("/")
        self._compression: ParquetCompression = config.get("compression") or DEFAULT_COMPRESSION
        self._fs: s3fs.S3FileSystem | None = None

    def _filesystem(self) -> s3fs.S3FileSystem:
        if self._fs is not None:
            return self._fs

        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        from posthog.models.integration import Integration  # noqa: PLC0415 — avoids a model import cycle

        integration = Integration.objects.get(id=self._ctx.integration_id, team_id=self._ctx.team_id)
        creds: S3CompatibleIntegration | AWSS3Integration
        if integration.kind == Integration.IntegrationKind.S3_COMPATIBLE:
            creds = S3CompatibleIntegration(integration)
            self._fs = s3fs.S3FileSystem(
                key=creds.aws_access_key_id,
                secret=creds.aws_secret_access_key,
                client_kwargs={"endpoint_url": creds.endpoint_url},
            )
        else:
            creds = AWSS3Integration(integration)
            self._fs = s3fs.S3FileSystem(
                key=creds.aws_access_key_id,
                secret=creds.aws_secret_access_key,
            )
        return self._fs

    def _object_key(self, batch_index: int) -> str:
        parts = [p for p in (self._prefix, self._ctx.table_name, self._ctx.run_uuid) if p]
        return f"{self._bucket}/{'/'.join(parts)}/part-{batch_index:04d}.parquet"

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        collected: list[pa.RecordBatch] = []
        async for batch in batches:
            collected.append(batch)

        if not collected:
            return BatchWriteOutcome(rows_written=0)

        table = pa.Table.from_batches(collected)
        key = self._object_key(ctx.batch_index)

        def write() -> int:
            buffer = io.BytesIO()
            pq.write_table(table, buffer, compression=self._compression)
            payload = buffer.getvalue()
            fs = self._filesystem()
            # Overwrite rather than append: the key is derived from the batch index, so a
            # re-applied batch replaces exactly what its previous attempt wrote.
            with fs.open(key, "wb") as f:
                f.write(payload)
            return len(payload)

        written_bytes = await sync_to_async(write, thread_sensitive=False)()
        return BatchWriteOutcome(rows_written=table.num_rows, bytes_written=written_bytes)

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Write a manifest listing the run's objects, so a reader can tell a run is complete."""
        return None

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        return None
