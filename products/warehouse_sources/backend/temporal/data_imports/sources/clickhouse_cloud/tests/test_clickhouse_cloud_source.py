from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.settings import (
    USAGE_COST_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.source import (
    ClickhouseCloudSource,
)


class TestClickhouseCloudSchemas:
    def test_all_endpoints_present(self) -> None:
        names = {s.name for s in ClickhouseCloudSource().get_schemas(MagicMock(), team_id=1)}
        assert names == {
            "organizations",
            "services",
            "usage_cost",
            "api_keys",
            "members",
            "activities",
            "backups",
        }

    def test_usage_cost_is_incremental_on_date_with_restatement_lookback(self) -> None:
        schema = next(s for s in ClickhouseCloudSource().get_schemas(MagicMock(), team_id=1) if s.name == "usage_cost")
        assert schema.supports_incremental is True
        assert schema.supports_append is False  # unlocked records get restated; append would duplicate
        assert [f["field"] for f in schema.incremental_fields] == ["date"]
        assert schema.default_incremental_lookback_seconds == USAGE_COST_LOOKBACK_SECONDS

    def test_activities_is_incremental_on_created_at(self) -> None:
        schema = next(s for s in ClickhouseCloudSource().get_schemas(MagicMock(), team_id=1) if s.name == "activities")
        assert schema.supports_incremental is True
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ["createdAt"]

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
