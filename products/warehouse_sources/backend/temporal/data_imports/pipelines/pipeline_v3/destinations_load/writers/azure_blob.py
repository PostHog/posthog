"""Delivering a run's batches to Azure Blob Storage.

The same idea as the S3 writer: each batch becomes one blob at a name derived from the run and
the batch index, so re-applying a batch overwrites its own blob rather than adding a second
copy. Nothing needs staging or a swap.

Connection handling comes from batch exports' Azure Blob destination:

- `_strip_leading_whitespace` plus `MalformedConnectionStringError` turn a connection string
  with a space after a `;` into an error that says what to fix, instead of a raw SDK
  `ValueError`.
- The client tuning is theirs too. `read_timeout` is the one that matters: the SDK default is
  60 seconds, which a single large block can exceed on a slow link.
- `_is_authorization_failure_response_error` is what separates "the credentials cannot write
  here" from a transient response error, so the first is reported as a permissions problem.

`AzureBlobConsumer` itself is not used, even though it touches no Temporal metric meter and so
would run outside an activity. Its `consume_chunk` accumulates the whole file in a `bytearray`
before uploading, which is the memory behavior this writer exists to avoid. Instead the parquet
is streamed a record batch at a time through `ParquetStreamTransformer`, whose
`write_record_batch` and `finish_parquet_file` are pure, and handed to `upload_blob` as an
async iterator. The SDK reads it in `max_block_size` blocks, so peak memory is one record batch
plus a few blocks rather than ~200 MiB of Arrow and two copies of its parquet.
"""

from __future__ import annotations

import json
import asyncio
import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import ClassVar, Literal

from django.conf import settings

import pyarrow as pa
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient, ContainerClient, ExponentialRetry

from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
    MalformedConnectionStringError,
    _get_azure_blob_integration,
    _is_authorization_failure_response_error,
    _strip_leading_whitespace,
)
from products.batch_exports.backend.temporal.destinations.constants import AZURE_BLOB_SUPPORTED_COMPRESSIONS
from products.batch_exports.backend.temporal.pipeline.transformer import ParquetStreamTransformer
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)

ParquetCompression = Literal["gzip", "brotli", "lz4", "zstd", "snappy", "none"]
DEFAULT_COMPRESSION: ParquetCompression = "zstd"

# The destination's `config` is an unvalidated JSONField, so whatever a user puts in it reaches
# pyarrow directly. Anything outside this set fails mid-write, several hundred MiB in.
SUPPORTED_COMPRESSIONS = frozenset(AZURE_BLOB_SUPPORTED_COMPRESSIONS["Parquet"]) | {"none"}

# Blobs larger than `MAX_SINGLE_PUT_SIZE` are uploaded in blocks of `MAX_BLOCK_SIZE`. A streamed
# upload has no known length, so it always takes the block path and the blob only appears once
# the block list is committed.
MAX_SINGLE_PUT_SIZE = 64 * 1024 * 1024
MAX_BLOCK_SIZE = 4 * 1024 * 1024
# The SDK default is 60 seconds, which a ~200 MiB batch can exceed.
READ_TIMEOUT_SECONDS = 600


class AzureBlobDestinationConfigurationError(ValueError):
    """The destination's config cannot produce a valid blob write."""


class ContainerNotFoundError(Exception):
    """Raised when the configured container does not exist.

    Containers are not created here, so this is the customer's to fix.
    """

    def __init__(self, container: str) -> None:
        super().__init__(
            f"The container '{container}' does not exist in this storage account. "
            "Create it, or point the destination at an existing container, then run the sync again."
        )


class MissingContainerPermissionsError(Exception):
    """Raised when the connection string cannot write to the container.

    Batch exports' own `MissingRequiredPermissionsError` says "batch export", which reads
    wrong on a sync. Only the classifier behind it is shared.
    """

    def __init__(self, container: str) -> None:
        super().__init__(
            f"These credentials cannot write to the container '{container}'. "
            "Give the connection string write access to it, then run the sync again."
        )


@dataclass(frozen=False, kw_only=True)
class _WriteStats:
    """What the parquet stream produced, read back after the upload has drained it."""

    rows: int = 0
    parquet_bytes: int = 0


async def _parquet_byte_stream(
    batches: AsyncIterator[pa.RecordBatch], compression: str | None, stats: _WriteStats
) -> AsyncIterator[bytes]:
    """Yield the parquet encoding of `batches`, one record batch at a time.

    `write_record_batch` returns only the bytes the writer produced for that batch and resets
    its buffer, so nothing accumulates. The pyarrow write runs in a thread to keep the event
    loop free for the upload it is feeding.
    """
    transformer = ParquetStreamTransformer(compression=compression, include_inserted_at=True)

    async for record_batch in batches:
        # No-op after the first batch. A batch that later grows a column is projected back onto
        # the first schema, because one parquet file has one schema.
        transformer.schema = record_batch.schema

        chunk = await asyncio.to_thread(transformer.write_record_batch, record_batch)
        stats.rows += record_batch.num_rows
        stats.parquet_bytes += len(chunk)
        if chunk:
            yield chunk

    footer = await asyncio.to_thread(transformer.finish_parquet_file)
    stats.parquet_bytes += len(footer)
    if footer:
        yield footer


async def _chain(head: pa.RecordBatch, rest: AsyncIterator[pa.RecordBatch]) -> AsyncIterator[pa.RecordBatch]:
    yield head
    async for record_batch in rest:
        yield record_batch


class AzureBlobDestinationWriter:
    """Writes a run's batches as parquet blobs under a prefix."""

    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._container: str = (config.get("container_name") or config.get("container") or "").strip("/")
        self._prefix: str = (config.get("prefix") or "").strip("/")
        self._compression: ParquetCompression = config.get("compression") or DEFAULT_COMPRESSION
        self._max_concurrency: int = settings.BATCH_EXPORT_AZURE_BLOB_MAX_CONCURRENT_UPLOADS

        self._validate_config()

    def _validate_config(self) -> None:
        """Reject a config that cannot write, before a batch is read.

        Left to fail later, a missing container writes to a nonsense name and an unsupported
        compression fails deep inside pyarrow, hundreds of MiB into the batch.
        """
        name = self._ctx.destination_name

        if not self._container:
            raise AzureBlobDestinationConfigurationError(
                f"Destination {name} has no container. Add a container to the destination, then run the sync again."
            )
        if self._compression not in SUPPORTED_COMPRESSIONS:
            supported = ", ".join(sorted(SUPPORTED_COMPRESSIONS))
            raise AzureBlobDestinationConfigurationError(
                f"Destination {name} uses the compression '{self._compression}', which parquet files cannot use. "
                f"Pick one of: {supported}."
            )

    # --- names ------------------------------------------------------------------------

    def _run_prefix(self) -> str:
        parts = [p for p in (self._prefix, self._ctx.table_name, self._ctx.run_uuid) if p]
        return f"{'/'.join(parts)}/"

    def _blob_name(self, batch_index: int) -> str:
        return f"{self._run_prefix()}part-{batch_index:04d}.parquet"

    def _manifest_name(self) -> str:
        return f"{self._run_prefix()}_manifest.json"

    # --- connection -------------------------------------------------------------------

    @asynccontextmanager
    async def _container_client(self) -> AsyncIterator[ContainerClient]:
        """Their client, entered so its transport is closed on the way out.

        A writer is built per batch, so a client left open here leaks a session per batch.
        """
        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        integration = await _get_azure_blob_integration(self._ctx.integration_id, self._ctx.team_id)

        try:
            service = BlobServiceClient.from_connection_string(
                conn_str=_strip_leading_whitespace(integration.connection_string),
                max_single_put_size=MAX_SINGLE_PUT_SIZE,
                max_block_size=MAX_BLOCK_SIZE,
                read_timeout=READ_TIMEOUT_SECONDS,
                retry_policy=ExponentialRetry(initial_backoff=15, increment_base=3, retry_total=3),
            )
        except ValueError:
            raise MalformedConnectionStringError()

        async with service:
            yield service.get_container_client(self._container)

    async def _upload(self, container: ContainerClient, name: str, data: AsyncIterator[bytes] | bytes) -> None:
        """Overwrite one blob, reporting the failures a customer can act on as themselves."""
        blob = container.get_blob_client(name)
        try:
            await blob.upload_blob(data, overwrite=True, max_concurrency=self._max_concurrency)
        except ResourceNotFoundError:
            raise ContainerNotFoundError(self._container)
        except HttpResponseError as err:
            if _is_authorization_failure_response_error(err):
                raise MissingContainerPermissionsError(self._container)
            raise

    # --- writer protocol ----------------------------------------------------------------

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        # The container is not created here. Creating one needs a permission the customer may
        # never have granted, and `prepare_run` runs before every batch, so concurrent batches
        # of the same run would race each other to create it. Batch exports does not create
        # containers either.
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        first = await anext(batches, None)
        if first is None:
            # No record batches at all. An empty blob is not a readable parquet file, so write
            # nothing rather than something a reader would choke on.
            return BatchWriteOutcome(rows_written=0)

        stats = _WriteStats()
        compression = None if self._compression == "none" else self._compression

        async with self._container_client() as container:
            # Overwrite: the name is derived from the batch index, so a re-applied batch
            # replaces exactly what its previous attempt wrote. The replacement happens when
            # the block list is committed, so a failed attempt never leaves a partial blob.
            await self._upload(
                container,
                self._blob_name(ctx.batch_index),
                _parquet_byte_stream(_chain(first, batches), compression, stats),
            )

        return BatchWriteOutcome(rows_written=stats.rows, bytes_written=stats.parquet_bytes)

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Write a manifest, which is how a reader tells a finished run from an abandoned one.

        It carries no file list. `finalize_run` runs on a writer that may have written none of
        the run's batches, so it has no record of what they were named.
        """
        manifest = {
            "run_uuid": ctx.run_uuid,
            "job_id": ctx.job_id,
            "schema_id": ctx.schema_id,
            "table": ctx.table_name,
            "sync_type": ctx.sync_type,
            "blob_prefix": self._run_prefix(),
            "blob_name_pattern": "part-<batch index, 4 digits>.parquet",
            "file_format": "parquet",
            "compression": self._compression,
            "completed_at": dt.datetime.now(dt.UTC).isoformat(),
        }

        async with self._container_client() as container:
            await self._upload(container, self._manifest_name(), json.dumps(manifest, indent=2).encode("utf-8"))

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        # Blobs an abandoned run already wrote are left where they are: they sit under that
        # run's own prefix, carry no manifest, and deleting them needs a permission we do not
        # ask for. The absence of the manifest is what tells a reader to ignore them.
        return None
