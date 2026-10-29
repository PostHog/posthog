from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.source import (
    ClickhouseCloudSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clickhousecloud import (
    ClickhouseCloudSourceConfig,
)


class TestClickhouseCloudSchemas:
    @parameterized.expand([("organizations",), ("services",), ("api_keys",), ("members",), ("backups",)])
    def test_snapshot_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # These list endpoints return complete unfiltered arrays — no server-side updated-since
        # filter exists, so they must not advertise incremental.
        schema = next(s for s in ClickhouseCloudSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_plumbs_transport_result(self, _name: str, transport_result: bool, expected: bool) -> None:
        config = ClickhouseCloudSourceConfig(key_id="key-id", key_secret="key-secret")
        with scripted_network([ScriptedResponse(status=200 if transport_result else 401)]) as network:
            ok, error = ClickhouseCloudSource().validate_credentials(config, team_id=1)
        assert ok is expected
        assert (error is None) is expected
        assert [request.path for request in network.requests_log] == ["/v1/organizations"]
        assert network.requests_log[0].headers["authorization"] == "Basic a2V5LWlkOmtleS1zZWNyZXQ="


class TestClickhouseCloudSourceForPipeline:
    @parameterized.expand(
        [
            ("organizations", ["id"], None),
            ("services", ["organizationId", "id"], None),
            ("usage_cost", ["organizationId", "date", "entityId"], "datetime"),
            ("members", ["organizationId", "userId"], None),
            ("activities", ["organizationId", "id"], "datetime"),
            ("backups", ["organizationId", "serviceId", "id"], "datetime"),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_mode: str | None
    ) -> None:
        driver = SourceDriver(
            ClickhouseCloudSource(), ClickhouseCloudSourceConfig(key_id="key-id", key_secret="key-secret")
        )
        result = driver.run(endpoint, [ScriptedResponse(json={"result": []})])
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        assert result.response.sort_mode == "asc"
        assert result.response.partition_mode == partition_mode
