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
