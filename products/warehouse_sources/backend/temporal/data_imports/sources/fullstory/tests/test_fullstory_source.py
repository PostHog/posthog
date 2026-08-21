import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.source import FullStorySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fullstory import (
    FullStorySourceConfig,
)


class TestFullStorySource:
    def setup_method(self):
        self.source = FullStorySource()
        self.team_id = 123
        self.config = FullStorySourceConfig(api_key="api-key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Fullstory API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.source.validate_fullstory_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
