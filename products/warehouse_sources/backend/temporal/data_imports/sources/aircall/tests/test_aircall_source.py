import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.source import AircallSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aircall import (
    AircallSourceConfig,
)


class TestAircallSource:
    def setup_method(self):
        self.source = AircallSource()
        self.team_id = 123
        self.config = AircallSourceConfig(api_id="api-id", api_token="api-token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Aircall API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aircall.source.validate_aircall_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_id, self.config.api_token)
