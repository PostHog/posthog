import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GreenhouseSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse import (
    GreenhouseResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source import GreenhouseSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {
    "candidates",
    "applications",
    "jobs",
    "job_posts",
    "offers",
    "scorecards",
    "scheduled_interviews",
    "users",
}
FULL_REFRESH_ENDPOINTS = {"departments", "offices", "sources", "rejection_reasons", "close_reasons"}


class TestGreenhouseSource:
    def setup_method(self) -> None:
        self.source = GreenhouseSource()
        self.team_id = 123
        self.config = GreenhouseSourceConfig(api_key="test_api_key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.GREENHOUSE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Greenhouse"
        assert config.label == "Greenhouse"
        assert config.releaseStatus == "alpha"
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/greenhouse.png"
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://harvest.greenhouse.io",
            "403 Client Error: Forbidden for url: https://harvest.greenhouse.io",
        ],
    )
    def test_non_retryable_errors_includes_greenhouse_key(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_non_retryable_errors_matches_observed_error_message(self) -> None:
        observed = "401 Client Error: Unauthorized for url: https://harvest.greenhouse.io/v1/candidates?per_page=500"
        assert any(key in observed for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.lever.co/v1/opportunities",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error: str) -> None:
        assert not any(key in other_vendor_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_split(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        appendable = {schema.name for schema in schemas if schema.supports_append}

        assert incremental == INCREMENTAL_ENDPOINTS
        assert appendable == INCREMENTAL_ENDPOINTS

    @pytest.mark.parametrize("endpoint", sorted(FULL_REFRESH_ENDPOINTS))
    def test_reference_endpoints_are_full_refresh(self, endpoint: str) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=[endpoint])
        assert len(schemas) == 1
        assert schemas[0].supports_incremental is False
        assert schemas[0].incremental_fields == []

    def test_candidates_advertises_created_and_updated_cursors(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["candidates"])
        fields = {field["field"] for field in schemas[0].incremental_fields}
        assert fields == {"created_at", "updated_at"}

    def test_applications_advertises_last_activity_cursor(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["applications"])
        fields = {field["field"] for field in schemas[0].incremental_fields}
        assert fields == {"created_at", "last_activity_at"}

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.validate_greenhouse_credentials"
    )
    def test_validate_credentials_at_source_create_accepts_forbidden(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        is_valid, error = self.source.validate_credentials(self.config, self.team_id, schema_name=None)

        assert is_valid is True
        assert error is None
        mock_validate.assert_called_once_with("test_api_key", accept_forbidden=True)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.validate_greenhouse_credentials"
    )
    def test_validate_credentials_per_schema_probes_endpoint_path(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(self.config, self.team_id, schema_name="candidates")

        mock_validate.assert_called_once_with("test_api_key", path="/candidates", accept_forbidden=False)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is GreenhouseResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.greenhouse_source")
    def test_source_for_pipeline_passes_incremental_inputs(self, mock_greenhouse_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "candidates"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.incremental_field = "updated_at"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_greenhouse_source.call_args.kwargs
        assert kwargs["api_key"] == "test_api_key"
        assert kwargs["endpoint"] == "candidates"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "updated_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.greenhouse_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(
        self, mock_greenhouse_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "departments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_greenhouse_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
