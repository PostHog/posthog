"""Delivering a run's batches to an S3-compatible bucket.

Each batch is written to a key derived from the run and the batch index, so re-applying one
overwrites its own object rather than appending a second copy. Nothing here needs a staging
area or a swap.

Credentials, the client and its config come from batch exports' S3 destination:

- `_get_s3_integration` resolves all three shapes an S3-family integration can take. A
  role-based AWS integration keeps `aws_role_arn` in `config` with an empty `sensitive_config`,
  so reading key credentials off it raises. The AssumeRole flow behind it
  (`get_credentials_using_user_aws_role`) also refuses a role whose policy has no external-id
  condition, which is what stops one customer from assuming another's role.
- `s3_client` builds the client with the bucket's region, a refreshable session for assumed
  roles, and `request_checksum_calculation="when_required"`. That last one is why R2, GCS and
  MinIO accept our uploads at all: they reject AWS's newer checksum headers.

What is not taken from there is the upload itself. `ConcurrentS3Consumer` times every part
through `ExecutionTimeRecorder`, which resolves a Temporal metric meter and raises outside an
activity. Delivery runs in the Postgres-queue load worker, not in an activity, so the parts are
uploaded here instead, keeping their `RequestTimeout` retry behavior.

Bytes are streamed a record batch at a time through `ParquetStreamTransformer`, whose
`write_record_batch` and `finish_parquet_file` are pure. Collecting the whole staged batch
first would hold ~200 MiB of Arrow plus two copies of its parquet, per destination.
"""

from __future__ import annotations

import json
import asyncio
import datetime as dt
import functools
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from django.conf import settings

import pyarrow as pa
import structlog
import botocore.exceptions

from posthog.models.integration import AWSS3RoleBasedIntegration, S3CompatibleIntegration
from posthog.models.team import Team

from products.batch_exports.backend.service import AWSCredentials
from products.batch_exports.backend.temporal.destinations.constants import S3_SUPPORTED_COMPRESSIONS
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    ConcurrentS3Consumer,
    IntermittentUploadPartTimeoutError,
    PolicyStatement,
    _get_s3_integration,
    get_credentials_using_user_aws_role,
    s3_client,
)
from products.batch_exports.backend.temporal.pipeline.transformer import ParquetStreamTransformer
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client
    from types_aiobotocore_s3.type_defs import CompletedPartTypeDef

logger = structlog.get_logger(__name__)

ParquetCompression = Literal["gzip", "brotli", "lz4", "zstd", "snappy", "none"]
DEFAULT_COMPRESSION: ParquetCompression = "zstd"

# The destination's `config` is an unvalidated JSONField, so whatever a user puts in it reaches
# pyarrow directly. Anything outside this set fails mid-write, several hundred MiB in.
SUPPORTED_COMPRESSIONS = frozenset(S3_SUPPORTED_COMPRESSIONS["Parquet"]) | {"none"}

# Same knob batch exports uploads its parts with, so both products buffer the same amount per
# in-flight upload.
PART_SIZE_BYTES = settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES

# `RequestTimeout` is S3 telling us the part took too long to arrive, which a retry usually
# fixes. Every other `ClientError` is a real failure and is raised as-is.
UPLOAD_MAX_ATTEMPTS = ConcurrentS3Consumer.UPLOAD_PART_MAX_ATTEMPTS
INITIAL_RETRY_DELAY = ConcurrentS3Consumer.INITIAL_RETRY_DELAY
MAX_RETRY_DELAY = ConcurrentS3Consumer.MAX_RETRY_DELAY
EXPONENTIAL_BACKOFF_COEFFICIENT = ConcurrentS3Consumer.EXPONENTIAL_BACKOFF_COEFFICIENT

RefreshCredentials = Callable[[], Awaitable[AWSCredentials]]


class S3DestinationConfigurationError(ValueError):
    """The destination's config cannot produce a valid S3 write."""


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


async def _retry_on_request_timeout(part_number: int, call: Callable[[], Awaitable[Any]]) -> Any:
    attempt = 0
    while True:
        attempt += 1
        try:
            return await call()
        except botocore.exceptions.ClientError as err:
            if err.response.get("Error", {}).get("Code") != "RequestTimeout":
                raise
            if attempt >= UPLOAD_MAX_ATTEMPTS:
                raise IntermittentUploadPartTimeoutError(part_number=part_number) from err

            delay = min(MAX_RETRY_DELAY, INITIAL_RETRY_DELAY * (attempt**EXPONENTIAL_BACKOFF_COEFFICIENT))
            logger.warning("s3_destination_part_timeout", part_number=part_number, attempt=attempt, retry_in=delay)
            await asyncio.sleep(delay)


class _ObjectUpload:
    """Writes one S3 object from a stream of bytes, holding at most one part in memory.

    A stream that fits in a single part is sent with `put_object`, which leaves nothing to
    orphan if the batch fails. Anything larger becomes a multi-part upload, whose parts only
    become an object once `complete` runs, so a failed attempt is never half-readable.
    """

    def __init__(self, client: S3Client, bucket: str, key: str, part_size: int = PART_SIZE_BYTES) -> None:
        self._client = client
        self._bucket = bucket
        self._key = key
        self._part_size = part_size
        self._buffer = bytearray()
        self._upload_id: str | None = None
        self._parts: list[CompletedPartTypeDef] = []
        self._next_part_number = 1

    async def feed(self, data: bytes) -> None:
        if not data:
            return

        self._buffer.extend(data)
        while len(self._buffer) >= self._part_size:
            await self._upload_part(bytes(self._buffer[: self._part_size]))
            del self._buffer[: self._part_size]

    async def complete(self) -> None:
        if self._upload_id is None:
            payload = bytes(self._buffer)
            self._buffer.clear()
            await _retry_on_request_timeout(
                1, lambda: self._client.put_object(Bucket=self._bucket, Key=self._key, Body=payload)
            )
            return

        if self._buffer:
            await self._upload_part(bytes(self._buffer))
            self._buffer.clear()

        await self._client.complete_multipart_upload(
            Bucket=self._bucket,
            Key=self._key,
            UploadId=self._upload_id,
            MultipartUpload={"Parts": self._parts},
        )

    async def abort(self) -> None:
        """Drop the parts of an upload that will not complete. Best effort."""
        if self._upload_id is None:
            return

        upload_id, self._upload_id = self._upload_id, None
        try:
            await self._client.abort_multipart_upload(Bucket=self._bucket, Key=self._key, UploadId=upload_id)
        except Exception:
            logger.warning("s3_destination_abort_failed", key=self._key, upload_id=upload_id, exc_info=True)

    async def _upload_part(self, data: bytes) -> None:
        if self._upload_id is None:
            response = await self._client.create_multipart_upload(Bucket=self._bucket, Key=self._key)
            self._upload_id = response["UploadId"]

        upload_id = self._upload_id
        part_number = self._next_part_number
        self._next_part_number += 1

        response = await _retry_on_request_timeout(
            part_number,
            lambda: self._client.upload_part(
                Bucket=self._bucket,
                Key=self._key,
                PartNumber=part_number,
                UploadId=upload_id,
                Body=data,
            ),
        )
        self._parts.append({"ETag": response["ETag"], "PartNumber": part_number})


class S3DestinationWriter:
    """Writes a run's batches as parquet objects under a prefix."""

    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._bucket: str = (config.get("bucket") or config.get("bucket_name") or "").strip("/")
        self._region: str = (config.get("region") or "").strip()
        self._prefix: str = (config.get("prefix") or "").strip("/")
        self._use_virtual_style_addressing = bool(config.get("use_virtual_style_addressing"))
        self._compression: ParquetCompression = config.get("compression") or DEFAULT_COMPRESSION

        self._validate_config()

    def _validate_config(self) -> None:
        """Reject a config that cannot write, before a batch is read.

        Left to fail later, a missing bucket writes to a nonsense key and an unsupported
        compression fails deep inside pyarrow, hundreds of MiB into the batch.
        """
        name = self._ctx.destination_name

        if not self._bucket:
            raise S3DestinationConfigurationError(
                f"Destination {name} has no bucket. Add a bucket to the destination, then run the sync again."
            )
        if not self._region:
            raise S3DestinationConfigurationError(
                f"Destination {name} has no region. Set the region the bucket is in, for example 'us-east-1', "
                "then run the sync again."
            )
        if self._compression not in SUPPORTED_COMPRESSIONS:
            supported = ", ".join(sorted(SUPPORTED_COMPRESSIONS))
            raise S3DestinationConfigurationError(
                f"Destination {name} uses the compression '{self._compression}', which parquet files cannot use. "
                f"Pick one of: {supported}."
            )

    # --- keys -------------------------------------------------------------------------

    def _run_prefix(self) -> str:
        parts = [p for p in (self._prefix, self._ctx.table_name, self._ctx.run_uuid) if p]
        return f"{'/'.join(parts)}/"

    def _object_key(self, batch_index: int) -> str:
        return f"{self._run_prefix()}part-{batch_index:04d}.parquet"

    def _manifest_key(self) -> str:
        return f"{self._run_prefix()}_manifest.json"

    # --- connection -------------------------------------------------------------------

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[S3Client]:
        """Their client, entered so its aiohttp session is closed on the way out.

        A writer is built per batch, so a client left open here leaks a session per batch.
        """
        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        integration = await _get_s3_integration(self._ctx.integration_id, self._ctx.team_id)

        endpoint_url: str | None = None
        refresh_credentials: RefreshCredentials | None = None

        if isinstance(integration, AWSS3RoleBasedIntegration):
            # A role-based integration holds no keys at all, only the customer's role ARN, so
            # credentials are assumed per run and refreshed as they expire.
            refresh_credentials = await self._role_credentials_refresher(integration)
            credentials = await refresh_credentials()
        else:
            credentials = AWSCredentials(
                aws_access_key_id=integration.aws_access_key_id,
                aws_secret_access_key=integration.aws_secret_access_key,
            )
            if isinstance(integration, S3CompatibleIntegration):
                endpoint_url = integration.endpoint_url

        async with s3_client(
            credentials,
            region=self._region,
            use_virtual_style_addressing=self._use_virtual_style_addressing,
            endpoint_url=endpoint_url,
            refresh_using=refresh_credentials,
        ) as client:
            yield client

    async def _role_credentials_refresher(self, integration: AWSS3RoleBasedIntegration) -> RefreshCredentials:
        """Assume the customer's role, narrowed to the keys this run writes.

        The external id is the organization's, the same one batch exports asks customers to
        put in their role's trust policy, so a role already set up for exports works here.
        """
        team = await Team.objects.aget(id=self._ctx.team_id)
        external_id = f"posthog-{team.organization_id}"

        policy_statements = [
            PolicyStatement(
                Effect="Allow",
                Action=["s3:PutObject", "s3:AbortMultipartUpload"],
                Resource=f"arn:aws:s3:::{self._bucket}/{self._run_prefix()}*",
            )
        ]

        return functools.partial(
            get_credentials_using_user_aws_role,
            integration.aws_role_arn,
            external_id,
            session_name=f"PostHog-warehouse-sync-{self._ctx.schema_id}",
            policy_statements=policy_statements,
        )

    # --- writer protocol ----------------------------------------------------------------

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        # A bucket is the customer's to create, and an object key needs nothing created ahead
        # of it. `prepare_run` runs before every batch, so anything done here is done per batch.
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        first = await anext(batches, None)
        if first is None:
            # No record batches at all. An empty object is not a readable parquet file, so
            # write nothing rather than something a reader would choke on.
            return BatchWriteOutcome(rows_written=0)

        stats = _WriteStats()
        key = self._object_key(ctx.batch_index)

        async with self._client() as client:
            # Overwrite rather than append: the key is derived from the batch index, so a
            # re-applied batch replaces exactly what its previous attempt wrote.
            upload = _ObjectUpload(client, self._bucket, key)
            try:
                async for chunk in _parquet_byte_stream(_chain(first, batches), self._pq_compression(), stats):
                    await upload.feed(chunk)
                await upload.complete()
            except Exception:
                await upload.abort()
                raise

        return BatchWriteOutcome(rows_written=stats.rows, bytes_written=stats.parquet_bytes)

    def _pq_compression(self) -> str | None:
        return None if self._compression == "none" else self._compression

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Write a manifest, which is how a reader tells a finished run from an abandoned one.

        It carries no file list. `finalize_run` runs on a writer that may have written none of
        the run's batches, and listing the prefix would need a permission neither the assumed
        role nor a customer's access key is asked for.
        """
        manifest = {
            "run_uuid": ctx.run_uuid,
            "job_id": ctx.job_id,
            "schema_id": ctx.schema_id,
            "table": ctx.table_name,
            "sync_type": ctx.sync_type,
            "object_prefix": self._run_prefix(),
            "object_key_pattern": "part-<batch index, 4 digits>.parquet",
            "file_format": "parquet",
            "compression": self._compression,
            "completed_at": dt.datetime.now(dt.UTC).isoformat(),
        }

        async with self._client() as client:
            await client.put_object(
                Bucket=self._bucket,
                Key=self._manifest_key(),
                Body=json.dumps(manifest, indent=2).encode("utf-8"),
            )

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        # Objects an abandoned run already wrote are left where they are: they sit under that
        # run's own prefix, carry no manifest, and deleting them needs a permission we do not
        # ask for. The absence of the manifest is what tells a reader to ignore them.
        return None
