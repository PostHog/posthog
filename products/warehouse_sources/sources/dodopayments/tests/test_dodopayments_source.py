import pytest

from products.warehouse_sources.sources.dodopayments._config import DodoPaymentsSourceConfig
from products.warehouse_sources.sources.dodopayments.source import DodoPaymentsSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, scripted_network


class TestDodoPaymentsSource:
    def setup_method(self):
        self.source = DodoPaymentsSource()
        self.team_id = 123
        self.config = DodoPaymentsSourceConfig(api_key="test-api-key", mode="live")

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message_fragment",
        [
            (429, False, "rate limiting"),
            (None, False, "Could not reach"),
        ],
    )
    def test_validate_credentials_maps_probe_results(
        self, status: int | None, expected_valid: bool, expected_message_fragment: str | None
    ) -> None:
        answer = ConnectionError("connection reset") if status is None else ScriptedResponse(status=status)
        with scripted_network(always(answer)) as network:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message
        assert network.requests_log[0].url == "https://live.dodopayments.com/customers?page_size=1"
        assert network.requests_log[0].headers["authorization"] == "Bearer test-api-key"
