import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wasabi import WasabiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.settings import (
    ENDPOINTS,
    UTILIZATION_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.source import WasabiSource


class TestWasabiSource:
    def setup_method(self) -> None:
        self.source = WasabiSource()
        self.team_id = 123
        self.config = WasabiSourceConfig(api_key="wasabi-key")

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", ["accounts", "sub_account_invoices"])
    def test_get_schemas_full_refresh_endpoints(self, endpoint: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []

    @pytest.mark.parametrize("endpoint", ["utilizations", "bucket_utilizations"])
    def test_get_schemas_incremental_endpoints_are_merge_only(self, endpoint: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is True
        # The date-window walk re-reads a boundary day each run, so append would duplicate rows.
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ["StartTime"]
        assert schema.default_incremental_lookback_seconds == UTILIZATION_LOOKBACK_SECONDS

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["utilizations"])
        assert [s.name for s in schemas] == ["utilizations"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://partner.wasabisys.com/v1/accounts",
            "403 Client Error: Forbidden for url: https://partner.wasabisys.com/v1/utilizations?from=2024-01-01",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://partner.wasabisys.com/v1/accounts",
            "429 Client Error: Too Many Requests for url: https://partner.wasabisys.com/v1/utilizations",
        ],
    )
    def test_non_retryable_errors_ignore_retryable_failures(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize("should_use_incremental_field", [True, False])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.source.wasabi_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_wasabi_source: mock.MagicMock, should_use_incremental_field: bool
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "utilizations"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2024-03-05T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_wasabi_source.call_args.kwargs
        assert kwargs["api_key"] == "wasabi-key"
        assert kwargs["endpoint"] == "utilizations"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        # The watermark is only forwarded when the sync is actually incremental.
        expected_last_value = "2024-03-05T00:00:00Z" if should_use_incremental_field else None
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
