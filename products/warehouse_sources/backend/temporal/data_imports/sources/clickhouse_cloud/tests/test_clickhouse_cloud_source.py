from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.source import (
    ClickhouseCloudSource,
)


class TestClickhouseCloudSchemas:
    @parameterized.expand([("organizations",), ("services",), ("api_keys",), ("members",), ("backups",)])
    def test_snapshot_endpoints_are_full_refresh_only(self, endpoint: str) -> None:
        # These list endpoints return complete unfiltered arrays — no server-side updated-since
        # filter exists, so they must not advertise incremental.
        schema = next(s for s in ClickhouseCloudSource().get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    def test_names_filter(self) -> None:
        schemas = ClickhouseCloudSource().get_schemas(MagicMock(), team_id=1, names=["usage_cost"])
        assert [s.name for s in schemas] == ["usage_cost"]


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_plumbs_transport_result(self, _name: str, transport_result: bool, expected: bool) -> None:
        config = MagicMock(key_id="key-id", key_secret="key-secret")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.source.validate_clickhouse_cloud_credentials",
            return_value=transport_result,
        ) as mock_validate:
            ok, error = ClickhouseCloudSource().validate_credentials(config, team_id=1)
        assert ok is expected
        assert (error is None) is expected
        mock_validate.assert_called_once_with("key-id", "key-secret")


class TestClickhouseCloudSourceForPipeline:
    def _response(self, endpoint: str) -> object:
        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.logger = MagicMock()
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = None
        config = MagicMock(key_id="key-id", key_secret="key-secret")
        return ClickhouseCloudSource().source_for_pipeline(config, MagicMock(), inputs)

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
        response = self._response(endpoint)
        assert response.name == endpoint  # type: ignore[attr-defined]
        assert response.primary_keys == primary_keys  # type: ignore[attr-defined]
        assert response.sort_mode == "asc"  # type: ignore[attr-defined]
        assert response.partition_mode == partition_mode  # type: ignore[attr-defined]
