import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SentineloneSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.sentinelone import (
    SentinelOneResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.source import SentineloneSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSentineloneSource:
    def setup_method(self):
        self.source = SentineloneSource()
        self.team_id = 123
        self.config = SentineloneSourceConfig(console_url="example.sentinelone.net", api_token="tok")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SENTINELONE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Sentinelone"
        assert config.label == "SentinelOne"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/sentinelone.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["console_url", "api_token"]

        console_field, token_field = config.fields
        assert isinstance(console_field, SourceFieldInputConfig)
        assert console_field.type == SourceFieldInputConfigType.TEXT
        assert console_field.secret is False

        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_console_url_is_a_connection_host_field(self):
        # Retargeting the console URL must force re-entry of the API token — otherwise a
        # member could point the stored token at a server they control.
        assert self.source.connection_host_fields == ["console_url"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("threats", True),
            ("agents", True),
            ("activities", True),
            ("groups", False),
            ("sites", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["threats"])
        assert len(schemas) == 1
        assert schemas[0].name == "threats"

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid SentinelOne API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.source.validate_sentinelone_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="threats")

        assert result == mock_return
        mock_validate.assert_called_once_with(self.config.console_url, self.config.api_token, "threats", self.team_id)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SentinelOneResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.source.sentinelone_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_sentinelone_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "threats"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_sentinelone_source.call_args.kwargs
        assert kwargs["console_url"] == "example.sentinelone.net"
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "threats"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.source.sentinelone_source"
    )
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_sentinelone_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "groups"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_sentinelone_source.call_args.kwargs["db_incremental_field_last_value"] is None
