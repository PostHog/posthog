from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from unittest import mock

import psycopg
import pyarrow as pa
import botocore.exceptions

from posthog.models.integration import IntegrationError

from products.batch_exports.backend.facade.destinations.postgres import PostgreSQLClient
from products.batch_exports.backend.facade.destinations.redshift import StringLimitExceededError
from products.batch_exports.backend.facade.destinations.s3 import (
    ExternalRoleArnNotConfiguredError,
    InvalidCredentialsError,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DestinationConfigurationError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.postgres import (
    UnrelatedTableExistsError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.redshift import (
    RedshiftDestinationWriter,
)


def _aws_error(code: str, operation: str = "GetClusterCredentials", status: int = 400) -> Exception:
    response: Any = {"Error": {"Code": code, "Message": "fake-secret"}, "ResponseMetadata": {"HTTPStatusCode": status}}
    return botocore.exceptions.ClientError(response, operation)


def _ctx() -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id="schema",
        source_id="source",
        job_id="job",
        run_uuid="run-a1",
        destination_id="destination",
        destination_type="Redshift",
        destination_name="test redshift",
        table_name="charges",
        sync_type="incremental",
        config={"schema": "public"},
    )


async def _batches() -> AsyncIterator[pa.RecordBatch]:
    yield pa.RecordBatch.from_pydict({"id": [1]})


class LocalRedshiftWriter(RedshiftDestinationWriter):
    def __init__(self, ctx: DestinationRunContext, client: PostgreSQLClient) -> None:
        super().__init__(ctx)
        self._fake = client

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[PostgreSQLClient]:
        yield self._fake


@pytest.mark.asyncio
class TestConfigurationErrors:
    @pytest.mark.parametrize("finalize", [False, True], ids=["write_batch", "finalize_run"])
    @pytest.mark.parametrize(
        "error,expected",
        [
            (psycopg.errors.InsufficientPrivilege("permission denied for schema fake-secret"), "USAGE and CREATE"),
            (psycopg.errors.InsufficientPrivilege("permission denied for table fake-secret"), "USAGE and CREATE"),
            (_aws_error("AccessDenied", "AssumeRole"), "cannot assume the role"),
            (InvalidCredentialsError("fake-secret"), "cannot assume the role"),
            (_aws_error("AccessDenied"), "redshift:GetClusterCredentials"),
            (_aws_error("AccessDeniedException", "GetCredentials"), "redshift-serverless:GetCredentials"),
            (_aws_error("InvalidClientTokenId"), "rejected the access key"),
            (_aws_error("ClusterNotFound"), "cannot find the Redshift cluster"),
            (_aws_error("ResourceNotFoundException", "GetCredentials"), "cannot find the Redshift cluster"),
        ],
    )
    async def test_permanent_errors_are_configuration_errors(
        self, error: Exception, expected: str, finalize: bool
    ) -> None:
        ctx = _ctx()
        client = mock.AsyncMock(spec=PostgreSQLClient)
        writer = LocalRedshiftWriter(ctx, client)
        client.adelete_table.side_effect = error

        with (
            mock.patch.object(writer, "_table_exists", return_value=False),
            mock.patch.object(writer, "_ensure_table", side_effect=error),
            pytest.raises(DestinationConfigurationError, match=expected) as caught,
        ):
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
            psycopg.OperationalError("fake-secret"),
            psycopg.errors.SerializationFailure("fake-secret"),
            psycopg.errors.DeadlockDetected("fake-secret"),
            psycopg.errors.QueryCanceled("fake-secret"),
            psycopg.errors.ConnectionTimeout("fake-secret"),
            psycopg.errors.AdminShutdown("fake-secret"),
            StringLimitExceededError("fake-secret", "charges", "public"),
            UnrelatedTableExistsError("fake-secret"),
            TimeoutError("fake-secret"),
            _aws_error("Throttling", "AssumeRole"),
            _aws_error("AccessDenied", status=500),
            _aws_error("InternalFailure", status=503),
            botocore.exceptions.EndpointConnectionError(endpoint_url="https://redshift.us-east-1.amazonaws.com"),
            ExternalRoleArnNotConfiguredError(),
        ],
    )
    async def test_transient_errors_propagate_unchanged(self, error: Exception, finalize: bool) -> None:
        ctx = _ctx()
        client = mock.AsyncMock(spec=PostgreSQLClient)
        writer = LocalRedshiftWriter(ctx, client)
        client.adelete_table.side_effect = error

        with (
            mock.patch.object(writer, "_table_exists", return_value=False),
            mock.patch.object(writer, "_ensure_table", side_effect=error),
            pytest.raises(type(error)) as caught,
        ):
            if finalize:
                await writer.finalize_run(ctx)
            else:
                await writer.write_batch(
                    _batches(), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False)
                )

        assert caught.value is error
        assert not isinstance(caught.value, DestinationConfigurationError)

    async def test_an_unusable_host_reports_what_to_fix(self) -> None:
        ctx = _ctx()
        writer = LocalRedshiftWriter(ctx, mock.AsyncMock(spec=PostgreSQLClient))
        error = IntegrationError("Redshift host 'db.example.com' is not a recognized AWS Redshift endpoint")

        with (
            mock.patch.object(writer, "_table_exists", return_value=False),
            mock.patch.object(writer, "_ensure_table", side_effect=error),
            pytest.raises(DestinationConfigurationError) as caught,
        ):
            await writer.write_batch(_batches(), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False))

        assert caught.value.detail == str(error)
