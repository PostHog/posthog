import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.source import DodoPaymentsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dodopayments import (
    DodoPaymentsSourceConfig,
)

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.dodopayments.source.api_client"


class TestDodoPaymentsSource:
    def setup_method(self):
        self.source = DodoPaymentsSource()
        self.team_id = 123
        self.config = DodoPaymentsSourceConfig(api_key="test-api-key", mode="live")

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message_fragment",
        [
            ((True, 200), True, None),
            ((False, 401), False, "rejected the API key"),
            ((False, 403), False, "permission to read"),
            ((False, 429), False, "rate limiting"),
            ((False, 500), False, "server error"),
            ((False, None), False, "Could not reach"),
        ],
    )
    @mock.patch(f"{API_CLIENT_PATCH}.validate_credentials")
    def test_validate_credentials_maps_probe_results(
        self, mock_validate, probe_result, expected_valid, expected_message_fragment
    ):
        mock_validate.return_value = probe_result

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message
        mock_validate.assert_called_once_with("test-api-key", "live")
