import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.clari.clari import ClariResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.clari.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clari.source import ClariSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClariSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestClariSource:
    def setup_method(self):
        self.source = ClariSource()
        self.team_id = 123
        self.config = ClariSourceConfig(api_key="key", forecast_id="fc-1")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CLARI

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Clari"
        assert config.label == "Clari"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/clari.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "forecast_id"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.clari.com/v4/audit/events",
            "403 Client Error: Forbidden for url: https://api.clari.com/v4/export/jobs/123",
            "404 Client Error: Not Found for url: https://api.clari.com/v4/export/forecast/bad-id",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://api.clari.com/v4/audit/events"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only audit events expose a server-side date filter.
        assert schemas["audit_events"].supports_incremental is True
        assert schemas["audit_events"].incremental_fields == INCREMENTAL_FIELDS["audit_events"]
        assert [f["field"] for f in schemas["audit_events"].incremental_fields] == ["eventTimestamp"]
        assert schemas["forecast"].supports_incremental is False
        assert schemas["forecast"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["forecast"])
        assert len(schemas) == 1
        assert schemas[0].name == "forecast"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.clari.source.validate_clari_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Clari credentials"
        mock_validate.assert_called_once_with("key")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ClariResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.clari.source.clari_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_clari_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "audit_events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_clari_source.assert_called_once()
        kwargs = mock_clari_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["forecast_id"] == "fc-1"
        assert kwargs["endpoint"] == "audit_events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.clari.source.clari_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_clari_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "forecast"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_clari_source.call_args.kwargs["db_incremental_field_last_value"] is None
