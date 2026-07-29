import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.fusionauth import (
    FusionAuthResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.source import FusionAuthSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fusionauth import (
    FusionAuthSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFusionAuthSource:
    def setup_method(self):
        self.source = FusionAuthSource()
        self.team_id = 123
        self.config = FusionAuthSourceConfig(base_url="https://auth.example.com", api_key="00token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.FUSIONAUTH

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "FusionAuth"
        assert config.label == "FusionAuth"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/fusionauth.png"
        assert config.category is not None

        field_names = [f.name for f in config.fields]
        assert field_names == ["base_url", "api_key"]

        url_field, key_field = config.fields
        assert isinstance(url_field, SourceFieldInputConfig)
        assert url_field.type == SourceFieldInputConfigType.TEXT
        assert url_field.secret is False
        assert url_field.required is True

        assert isinstance(key_field, SourceFieldInputConfig)
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["base_url"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("Users", False),
            ("AuditLogs", True),
            ("EventLogs", True),
            ("LoginRecords", True),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_users_schema_has_window_cap_description(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "10,000" in (schemas["Users"].description or "")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Users"])
        assert len(schemas) == 1
        assert schemas[0].name == "Users"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected",
        [
            ((True, None), (True, None)),
            ((False, "Invalid FusionAuth API key"), (False, "Invalid FusionAuth API key")),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.source.validate_fusionauth_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == expected
        mock_validate.assert_called_once_with(self.config.base_url, self.config.api_key, self.team_id)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FusionAuthResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.source.fusionauth_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_fusionauth_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "AuditLogs"
        inputs.team_id = 42
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000000
        inputs.db_incremental_field_earliest_value = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_fusionauth_source.assert_called_once()
        kwargs = mock_fusionauth_source.call_args.kwargs
        assert kwargs["base_url"] == "https://auth.example.com"
        assert kwargs["api_key"] == "00token"
        assert kwargs["endpoint"] == "AuditLogs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["job_id"] == "job-1"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000000
        assert kwargs["db_incremental_field_earliest_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.source.fusionauth_source")
    def test_source_for_pipeline_omits_incremental_values_when_not_incremental(self, mock_fusionauth_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.db_incremental_field_earliest_value = "ignored"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_fusionauth_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["db_incremental_field_earliest_value"] is None
