import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartlead import (
    SmartleadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.source import SmartleadSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.source.validate_smartlead_credentials"
)


class TestSmartleadSource:
    def setup_method(self):
        self.source = SmartleadSource()
        self.team_id = 123
        self.config = SmartleadSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Smartlead API key"),
            ((False, 403), False, "Could not connect to Smartlead with the provided API key"),
            ((False, None), False, "Could not connect to Smartlead with the provided API key"),
        ],
    )
    @mock.patch(VALIDATE_PATCH)
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
