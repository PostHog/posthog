import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.source import CronitorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cronitor import (
    CronitorSourceConfig,
)


class TestCronitorSource:
    def setup_method(self):
        self.source = CronitorSource()
        self.team_id = 123
        self.config = CronitorSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            (
                (False, 401),
                False,
                "Cronitor rejected your API key. Copy the full key from Settings → API keys in your Cronitor account, then try again.",
            ),
            (
                (False, 403),
                False,
                "Your Cronitor API key is missing the monitor:read scope. Update the key's scopes in Cronitor, then reconnect.",
            ),
            ((False, None), False, "Could not connect to Cronitor with the provided API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.source.validate_cronitor_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
