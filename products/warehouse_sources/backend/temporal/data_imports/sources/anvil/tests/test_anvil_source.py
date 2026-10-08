import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.source import AnvilSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.anvil import AnvilSourceConfig


class TestAnvilSource:
    def setup_method(self):
        self.source = AnvilSource()
        self.team_id = 123
        self.config = AnvilSourceConfig(api_key="key-1")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Anvil rejected the API key"), False, "Anvil rejected the API key"),
            ((False, None), False, "Invalid Anvil API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.anvil.source.validate_anvil_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key-1")
