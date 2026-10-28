from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from unittest import mock

import pyarrow as pa
import botocore.exceptions

from products.batch_exports.backend.facade.destinations.s3 import (
    ExternalRoleArnNotConfiguredError,
    IntermittentUploadPartTimeoutError,
    InvalidCredentialsError,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DestinationConfigurationError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.s3 import (
    S3DestinationWriter,
)

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client


def _ctx() -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id="schema",
        source_id="source",
        job_id="job",
        run_uuid="run-a1",
        destination_id="destination",
        destination_type="S3",
        destination_name="test s3",
        table_name="charges",
        sync_type="full_refresh",
        integration_id=42,
        config={"bucket": "example-bucket", "region": "us-east-1"},
    )


def _client_error(code: str, operation: str = "PutObject", status: int = 403) -> botocore.exceptions.ClientError:
    response: Any = {"Error": {"Code": code, "Message": "fake-secret"}, "ResponseMetadata": {"HTTPStatusCode": status}}
    return botocore.exceptions.ClientError(response, operation)


async def _batches() -> AsyncIterator[pa.RecordBatch]:
    yield pa.RecordBatch.from_pydict({"id": [1]})


class LocalS3Writer(S3DestinationWriter):
    def __init__(self, ctx: DestinationRunContext, client: S3Client, connection_error: Exception | None) -> None:
        super().__init__(ctx)
        self._fake = client
        self._connection_error = connection_error

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[S3Client]:
        if self._connection_error is not None:
            raise self._connection_error
        yield self._fake


@pytest.mark.asyncio
class TestConfigurationErrors:
    @pytest.mark.parametrize("finalize", [False, True], ids=["write_batch", "finalize_run"])
    @pytest.mark.parametrize(
        ("error", "detail_word", "at_connect"),
        [
            (_client_error("InvalidAccessKeyId"), "access key ID", False),
            (_client_error("SignatureDoesNotMatch"), "access key ID", False),
            (_client_error("NoSuchBucket"), "bucket name and region", False),
            (_client_error("AccessDenied"), "s3:PutObject", False),
            (_client_error("AccessDeniedException"), "s3:AbortMultipartUpload", False),
            (_client_error("AccessDenied", "AssumeRole"), "trust policy", True),
            (_client_error("AccessDeniedException", "AssumeRole"), "external ID", True),
            (InvalidCredentialsError("fake-secret"), "trust policy", True),
            (
                botocore.exceptions.ParamValidationError(report='Invalid bucket name "foo": fake-secret'),
                "bucket name, region and prefix",
                False,
            ),
        ],
    )
    async def test_permanent_errors_are_configuration_errors(
        self, error: Exception, detail_word: str, at_connect: bool, finalize: bool
    ) -> None:
        ctx = _ctx()
        client = mock.AsyncMock()
        client.put_object.side_effect = error
        writer = LocalS3Writer(ctx, client, error if at_connect else None)

        with pytest.raises(DestinationConfigurationError, match=detail_word) as caught:
            if finalize:
                await writer.finalize_run(ctx)
            else:
                await writer.write_batch(
                    _batches(), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False)
                )

        assert str(caught.value).startswith(f"{ctx.destination_name}:")
        assert caught.value.__cause__ is error
        assert str(error) not in caught.value.detail
        assert "fake-secret" not in caught.value.detail

    @pytest.mark.parametrize("finalize", [False, True], ids=["write_batch", "finalize_run"])
    @pytest.mark.parametrize(
        "error",
        [
            _client_error("RequestTimeout"),
            _client_error("SlowDown"),
            _client_error("ServiceUnavailable", status=503),
            _client_error("InternalError", status=500),
            _client_error("AccessDenied", status=500),
            _client_error("NoSuchBucket", status=502),
            _client_error("InvalidAccessKeyId", status=503),
            _client_error("Throttling", "AssumeRole"),
            _client_error("ThrottlingException", "AssumeRole"),
            _client_error("RequestLimitExceeded"),
            _client_error("UnknownError"),
            IntermittentUploadPartTimeoutError(1),
            botocore.exceptions.EndpointConnectionError(endpoint_url="https://example.com"),
            botocore.exceptions.ConnectTimeoutError(endpoint_url="https://example.com"),
            botocore.exceptions.ReadTimeoutError(endpoint_url="https://example.com"),
            ExternalRoleArnNotConfiguredError(),
            TimeoutError("fake-secret"),
        ],
    )
    async def test_transient_errors_propagate_unchanged(self, error: Exception, finalize: bool) -> None:
        ctx = _ctx()
        writer = LocalS3Writer(ctx, mock.AsyncMock(), error)

        with pytest.raises(type(error)) as caught:
            if finalize:
                await writer.finalize_run(ctx)
            else:
                await writer.write_batch(
                    _batches(), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False)
                )

        assert caught.value is error
        assert not isinstance(caught.value, DestinationConfigurationError)

    async def test_bucket_name_whitespace_is_trimmed(self) -> None:
        # A bucket name pasted with a stray leading/trailing space fails S3's name regex with
        # no retry able to fix it. Trimming it here is the difference between that and a
        # working sync.
        ctx = dataclasses.replace(_ctx(), config={"bucket": " example-bucket ", "region": "us-east-1"})
        client = mock.AsyncMock()
        writer = LocalS3Writer(ctx, client, connection_error=None)

        await writer.write_batch(_batches(), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False))

        assert client.put_object.call_args.kwargs["Bucket"] == "example-bucket"
