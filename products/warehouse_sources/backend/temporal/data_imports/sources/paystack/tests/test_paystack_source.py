import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paystack import (
    PaystackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.source import PaystackSource


class TestPaystackSource:
    def setup_method(self):
        self.source = PaystackSource()
        self.team_id = 123
        self.config = PaystackSourceConfig(secret_api_key="sk_test_x")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Paystack secret API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.paystack.source.validate_paystack_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.secret_api_key)
