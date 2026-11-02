import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.source import (
    CampaignMonitorSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campaignmonitor import (
    CampaignMonitorSourceConfig,
)


class TestCampaignMonitorSource:
    def setup_method(self) -> None:
        self.source = CampaignMonitorSource()
        self.team_id = 123
        self.config = CampaignMonitorSourceConfig(api_key="test-key", client_id="client-abc")

    def test_client_id_is_a_connection_host_field(self) -> None:
        # Changing the targeted client must force the API key to be re-entered.
        assert "client_id" in self.source.connection_host_fields

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Campaign Monitor API key"),
        ],
    )
    def test_validate_credentials(self, probe_result: bool, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=200 if probe_result else 401)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.path for request in network.requests_log] == ["/api/v3.3/clients.json"]
        assert network.requests_log[0].headers["authorization"] == "Basic dGVzdC1rZXk6eA=="
