import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.source import (
    CampaignMonitorSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campaignmonitor import (
    CampaignMonitorSourceConfig,
)


class TestCampaignMonitorSource:
    def setup_method(self):
        self.source = CampaignMonitorSource()
        self.team_id = 123
        self.config = CampaignMonitorSourceConfig(api_key="test-key", client_id="client-abc")

    def test_client_id_is_a_connection_host_field(self):
        # Changing the targeted client must force the API key to be re-entered.
        assert "client_id" in self.source.connection_host_fields

    def test_get_schemas_full_refresh_until_incremental_verified(self):
        # No endpoint advertises incremental yet (server-side date filter unverified live).
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

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
