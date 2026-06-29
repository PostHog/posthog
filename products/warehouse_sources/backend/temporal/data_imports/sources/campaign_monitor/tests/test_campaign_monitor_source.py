import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.campaign_monitor import (
    CampaignMonitorResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.source import (
    CampaignMonitorSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    CampaignMonitorSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCampaignMonitorSource:
    def setup_method(self):
        self.source = CampaignMonitorSource()
        self.team_id = 123
        self.config = CampaignMonitorSourceConfig(api_key="test-key", client_id="client-abc")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CAMPAIGNMONITOR

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "CampaignMonitor"
        assert config.label == "Campaign Monitor"
        assert config.releaseStatus == "alpha"
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/campaign_monitor.png"

        fields = config.fields
        assert len(fields) == 2

        api_key_field, client_id_field = fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        assert isinstance(client_id_field, SourceFieldInputConfig)
        assert client_id_field.name == "client_id"
        assert client_id_field.type == SourceFieldInputConfigType.TEXT
        assert client_id_field.required is True

    def test_client_id_is_a_connection_host_field(self):
        # Changing the targeted client must force the API key to be re-entered.
        assert "client_id" in self.source.connection_host_fields

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url",
            "403 Client Error: Forbidden for url",
        ],
    )
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_full_refresh_until_incremental_verified(self):
        # No endpoint advertises incremental yet (server-side date filter unverified live).
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["clients"])

        assert len(schemas) == 1
        assert schemas[0].name == "clients"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Campaign Monitor API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.source.validate_campaign_monitor_credentials"
    )
    def test_validate_credentials(self, mock_validate, probe_result, expected_valid, expected_message):
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CampaignMonitorResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.source.campaign_monitor_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "campaigns"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-key",
            client_id="client-abc",
            endpoint="campaigns",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
