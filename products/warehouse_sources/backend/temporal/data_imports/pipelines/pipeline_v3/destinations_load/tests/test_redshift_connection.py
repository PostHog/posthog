from typing import Any

import pytest
from unittest import mock

from posthog.integrations import IntegrationRecord
from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DestinationConfigurationError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.redshift import (
    RedshiftDestinationWriter,
)

CLUSTER_HOST = "my-cluster.abc123.us-east-1.redshift.amazonaws.com"
WORKGROUP_HOST = "my-wg.123456789012.us-east-1.redshift-serverless.amazonaws.com"


def _ctx(**config: Any) -> DestinationRunContext:
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
        config={"database": "analytics", "schema": "public", **config},
        integration_id=7,
    )


def _password_integration() -> Integration:
    return Integration(
        kind=Integration.IntegrationKind.AWS_REDSHIFT,
        config={"host": "stored.example.com", "port": 5555, "user": "stored_user", "ssl_mode": "require"},
        sensitive_config={"password": "stored-password"},
    )


def _access_key_integration() -> Integration:
    return Integration(
        kind=Integration.IntegrationKind.AWS_REDSHIFT,
        config={"name": "keys", "user": "posthog", "groups": ["loaders"]},
        sensitive_config={"aws_access_key_id": "AKIAEXAMPLE", "aws_secret_access_key": "fake-secret"},
    )


class LocalRedshiftWriter(RedshiftDestinationWriter):
    def __init__(self, ctx: DestinationRunContext, integration: Integration) -> None:
        super().__init__(ctx)
        self._integration = integration

    async def _load_integration(self, integration_id: int) -> IntegrationRecord:
        return self._integration


def _aws_session(aws: mock.MagicMock) -> mock.MagicMock:
    client = mock.MagicMock()
    client.__aenter__.return_value = aws
    client.__aexit__.return_value = None
    session = mock.MagicMock()
    session.client.return_value = client
    return session


@pytest.mark.asyncio
class TestRedshiftConnection:
    async def test_a_password_connection_uses_its_own_host_and_ignores_the_config(self) -> None:
        writer = LocalRedshiftWriter(_ctx(host=CLUSTER_HOST, port=5439), _password_integration())

        with mock.patch("aioboto3.Session") as session:
            client = await writer._make_client()

        session.assert_not_called()
        assert (client.host, client.port, client.user, client.password, client.database) == (
            "stored.example.com",
            5555,
            "stored_user",
            "stored-password",
            "analytics",
        )

    @pytest.mark.parametrize(
        "config,port,service",
        [
            ({"host": CLUSTER_HOST}, 5439, "redshift"),
            ({"host": CLUSTER_HOST, "port": 5440}, 5440, "redshift"),
            ({"host": WORKGROUP_HOST}, 5439, "redshift-serverless"),
        ],
        ids=["cluster_default_port", "cluster_custom_port", "serverless_workgroup"],
    )
    async def test_an_access_key_connection_signs_in_with_temporary_credentials_on_the_config_host(
        self, config: dict[str, Any], port: int, service: str
    ) -> None:
        writer = LocalRedshiftWriter(_ctx(**config), _access_key_integration())
        aws = mock.MagicMock()
        aws.get_cluster_credentials = mock.AsyncMock(
            return_value={"DbUser": "IAM:posthog", "DbPassword": "temporary-password"}
        )
        aws.get_credentials = mock.AsyncMock(return_value={"dbUser": "IAM:posthog", "dbPassword": "temporary-password"})

        with mock.patch("aioboto3.Session", return_value=_aws_session(aws)) as session:
            client = await writer._make_client()

        assert session.call_args.kwargs["aws_access_key_id"] == "AKIAEXAMPLE"
        assert session.return_value.client.call_args.args == (service,)
        assert (client.host, client.port, client.user, client.password, client.database) == (
            config["host"],
            port,
            "IAM:posthog",
            "temporary-password",
            "analytics",
        )
        if service == "redshift":
            assert aws.get_cluster_credentials.call_args.kwargs == {
                "DbUser": "posthog",
                "DbName": "analytics",
                "ClusterIdentifier": "my-cluster",
                "DurationSeconds": 3600,
                "DbGroups": ["loaders"],
            }

    async def test_an_aws_connection_without_a_host_is_a_configuration_error(self) -> None:
        ctx = _ctx()
        writer = LocalRedshiftWriter(ctx, _access_key_integration())

        with mock.patch("aioboto3.Session") as session, pytest.raises(DestinationConfigurationError) as caught:
            await writer.write_batch(
                mock.MagicMock(), DestinationBatchContext(run=ctx, batch_index=0, is_final_batch=False)
            )

        session.assert_not_called()
        assert "host" in caught.value.detail
