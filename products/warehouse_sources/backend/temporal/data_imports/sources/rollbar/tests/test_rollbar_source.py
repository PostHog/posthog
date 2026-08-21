import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rollbar import (
    RollbarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.source import RollbarSource


class TestRollbarSource:
    def setup_method(self):
        self.source = RollbarSource()
        self.team_id = 123
        self.config = RollbarSourceConfig(access_token="access-token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Rollbar project access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.source.validate_rollbar_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_token)
