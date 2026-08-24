"""Delivering a run's batches to Azure Blob Storage.

The same idea as the S3 writer: each batch becomes one blob at a key derived from the run and
the batch index, so re-applying a batch overwrites its own blob rather than adding a second
copy. Nothing needs staging or a swap.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import ClassVar, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async
from azure.storage.blob import BlobServiceClient

from posthog.models.integration.azure_blob import AzureBlobIntegration

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)

ParquetCompression = Literal["gzip", "bz2", "brotli", "lz4", "zstd", "snappy", "none"]
DEFAULT_COMPRESSION: ParquetCompression = "zstd"


class AzureBlobDestinationWriter:
    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._container = config.get("container_name") or config.get("container") or ""
        self._prefix = (config.get("prefix") or "").strip("/")
        self._compression: ParquetCompression = config.get("compression") or DEFAULT_COMPRESSION
        self._client: BlobServiceClient | None = None

    def _service(self) -> BlobServiceClient:
        if self._client is not None:
            return self._client

        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        from posthog.models.integration import Integration  # noqa: PLC0415 — avoids a model import cycle

        integration = Integration.objects.get(id=self._ctx.integration_id, team_id=self._ctx.team_id)
        creds = AzureBlobIntegration(integration)
        self._client = BlobServiceClient.from_connection_string(creds.connection_string)
        return self._client

    def _blob_name(self, batch_index: int) -> str:
        parts = [p for p in (self._prefix, self._ctx.table_name, self._ctx.run_uuid) if p]
        return f"{'/'.join(parts)}/part-{batch_index:04d}.parquet"

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        def ensure_container() -> None:
            service = self._service()
            container = service.get_container_client(self._container)
            if not container.exists():
                container.create_container()

        await sync_to_async(ensure_container, thread_sensitive=False)()

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        collected: list[pa.RecordBatch] = []
        async for batch in batches:
            collected.append(batch)
        if not collected:
            return BatchWriteOutcome(rows_written=0)

        table = pa.Table.from_batches(collected)
        name = self._blob_name(ctx.batch_index)

        def write() -> int:
            buffer = io.BytesIO()
            pq.write_table(table, buffer, compression=self._compression)
            payload = buffer.getvalue()
            blob = self._service().get_blob_client(container=self._container, blob=name)
            # Overwrite: the name is derived from the batch index, so a re-applied batch replaces
            # exactly what its previous attempt wrote.
            blob.upload_blob(payload, overwrite=True)
            return len(payload)

        written_bytes = await sync_to_async(write, thread_sensitive=False)()
        return BatchWriteOutcome(rows_written=table.num_rows, bytes_written=written_bytes)

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        return None

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        return None
