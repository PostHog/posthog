import pytest
from unittest import mock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yoco import YocoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source import YocoSource


class TestYocoSource:
    def setup_method(self) -> None:
        self.source = YocoSource()
        self.team_id = 123
        self.config = YocoSourceConfig(api_key="yoco-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Yoco"
        assert config.category == DataWarehouseSourceCategory.PAYMENTS___BILLING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/yoco.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    @pytest.mark.parametrize(
        "name,expected_fields",
        [
            ("payments", ["updated_at", "created_at"]),
            ("orders", ["updated_at", "created_at"]),
            ("payouts", ["updated_at", "created_at"]),
            # Modifier groups have no updated_at at all, so only created_at is filterable.
            ("modifier_groups", ["created_at"]),
            # Locations and payout entries take no date filters — client-side filtering would
            # cost a full scan per sync, so they stay full refresh.
            ("locations", []),
            ("payout_entries", []),
        ],
    )
    def test_get_schemas_incremental_fields(self, name: str, expected_fields: list[str]) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert [f["field"] for f in schemas[name].incremental_fields] == expected_fields
        assert schemas[name].supports_incremental is bool(expected_fields)

    @pytest.mark.parametrize(
        "observed_error,expect_match",
        [
            ("401 Client Error: Unauthorized for url: https://api.yoco.com/v1/payments/", True),
            ("403 Client Error: Forbidden for url: https://api.yoco.com/v1/payouts/", True),
            ("500 Server Error: Internal Server Error for url: https://api.yoco.com/v1/payments/", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source.api_client")
    def test_get_endpoint_permissions_plumbs_endpoints(self, mock_client: mock.MagicMock) -> None:
        mock_client.get_endpoint_permissions.return_value = {"payments": None}
        assert self.source.get_endpoint_permissions(self.config, self.team_id, ["payments"]) == {"payments": None}
        assert mock_client.get_endpoint_permissions.call_args.args == ("yoco-key", ["payments"])

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.yoco.source.api_client")
    def test_source_for_pipeline_plumbs_arguments(self, mock_client: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "payments"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "created_at"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_client.yoco_source.call_args.kwargs
        assert kwargs["api_key"] == "yoco-key"
        assert kwargs["endpoint"] == "payments"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        # The user's chosen cursor must reach the request layer, not the endpoint default.
        assert kwargs["incremental_field"] == "created_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
