import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.optimizely import (
    OptimizelySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.source import OptimizelySource


class TestOptimizelySource:
    def setup_method(self):
        self.source = OptimizelySource()
        self.team_id = 123
        self.config = OptimizelySourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Optimizely personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.source.validate_optimizely_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)
