import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source import CloudabilitySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudability import (
    CloudabilitySourceConfig,
)


class TestCloudabilitySource:
    def setup_method(self):
        self.source = CloudabilitySource()
        self.team_id = 123
        self.config = CloudabilitySourceConfig(api_key="key", region="us", view_id=None)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid credentials. Check your API key and region."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source.validate_cloudability_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)
