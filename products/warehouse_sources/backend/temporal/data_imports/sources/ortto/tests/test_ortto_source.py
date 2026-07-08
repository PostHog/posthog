import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OrttoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.ortto import OrttoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source import OrttoSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOrttoSource:
    def setup_method(self):
        self.source = OrttoSource()
        self.team_id = 123
        self.config = OrttoSourceConfig(api_key="key", region="eu")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ORTTO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Ortto"
        assert config.label == "Ortto"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/ortto.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["region", "api_key"]

    def test_region_field_is_a_select_with_default(self):
        config = self.source.get_source_config
        region_field = next(f for f in config.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "global"
        assert {option.value for option in region_field.options} == {"global", "au", "eu"}

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.ap3api.com/v1/person/get",
            "403 Client Error: Forbidden for url: https://api.eu.ap3api.com/v1/accounts/get",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://api.ap3api.com/v1/person/get"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No endpoint exposes a server-side updated-since filter — everything full refresh.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["people"])
        assert len(schemas) == 1
        assert schemas[0].name == "people"

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
        "products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source.validate_ortto_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Ortto credentials"
        mock_validate.assert_called_once_with("eu", "key")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OrttoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ortto.source.ortto_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_ortto_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "people"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_ortto_source.assert_called_once()
        kwargs = mock_ortto_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "people"
        assert kwargs["resumable_source_manager"] is manager
