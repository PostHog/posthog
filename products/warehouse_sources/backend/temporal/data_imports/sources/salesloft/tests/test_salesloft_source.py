import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SalesLoftSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft import SalesloftResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.settings import (
    ENDPOINTS,
    SALESLOFT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.source import SalesLoftSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = sorted(name for name, c in SALESLOFT_ENDPOINTS.items() if c.incremental)
FULL_REFRESH_ENDPOINTS = sorted(name for name, c in SALESLOFT_ENDPOINTS.items() if not c.incremental)


def _make_inputs(schema_name: str = "people", **overrides):
    defaults = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestSalesLoftSource:
    def setup_method(self):
        self.source = SalesLoftSource()
        self.team_id = 123
        self.config = SalesLoftSourceConfig(api_key="sl_test_token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SALESLOFT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "SalesLoft"
        assert config.label == "Salesloft"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Shipped hidden until verified against a live account.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/salesloft.png"
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
            "401 Client Error: Unauthorized for url",
            "403 Client Error: Forbidden for url",
        ],
    )
    def test_non_retryable_errors_includes_key(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_non_retryable_errors_matches_observed_error_message(self):
        observed_error = "401 Client Error: Unauthorized for url: https://api.salesloft.com/v2/people?page=1"

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert len(schemas) == 28

    @pytest.mark.parametrize("name", INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoints_advertise_updated_at(self, name):
        by_name = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = by_name[name]

        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {f["field"] for f in schema.incremental_fields} == {"updated_at"}

    @pytest.mark.parametrize("name", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_have_no_incremental_field(self, name):
        by_name = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = by_name[name]

        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["people", "accounts"])

        assert {s.name for s in schemas} == {"people", "accounts"}

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Salesloft API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.source.validate_salesloft_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SalesloftResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.source.salesloft_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_salesloft_source):
        inputs = _make_inputs(
            schema_name="people",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00.000000Z",
            incremental_field="updated_at",
        )
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_salesloft_source.assert_called_once()
        kwargs = mock_salesloft_source.call_args.kwargs
        assert kwargs["api_key"] == "sl_test_token"
        assert kwargs["endpoint"] == "people"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000000Z"
        assert kwargs["incremental_field"] == "updated_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.source.salesloft_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_salesloft_source):
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00.000000Z",
        )

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_salesloft_source.call_args.kwargs["db_incremental_field_last_value"] is None
