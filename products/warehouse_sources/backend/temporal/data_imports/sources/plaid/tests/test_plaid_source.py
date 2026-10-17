import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plaid import PlaidSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.source import PlaidSource


class TestPlaidSource:
    def setup_method(self):
        self.source = PlaidSource()
        self.team_id = 123
        self.config = PlaidSourceConfig(environment="production", client_id="cid", secret="sec", access_token="tok")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Plaid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.plaid.source.validate_plaid_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("production", "cid", "sec", "tok")
