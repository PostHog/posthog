import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.torii import ToriiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.source import ToriiSource


class TestToriiSource:
    def setup_method(self):
        self.source = ToriiSource()
        self.team_id = 123
        self.config = ToriiSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.torii.source.validate_torii_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
