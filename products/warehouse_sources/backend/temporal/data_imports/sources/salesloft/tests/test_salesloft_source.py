import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.salesloft import (
    SalesLoftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.settings import SALESLOFT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.source import SalesLoftSource

INCREMENTAL_ENDPOINTS = sorted(name for name, c in SALESLOFT_ENDPOINTS.items() if c.incremental)
FULL_REFRESH_ENDPOINTS = sorted(name for name, c in SALESLOFT_ENDPOINTS.items() if not c.incremental)


class TestSalesLoftSource:
    def setup_method(self):
        self.source = SalesLoftSource()
        self.team_id = 123
        self.config = SalesLoftSourceConfig(api_key="sl_test_token")

    def test_non_retryable_errors_matches_observed_error_message(self):
        observed_error = "401 Client Error: Unauthorized for url: https://api.salesloft.com/v2/people?page=1"

        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Salesloft API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.source.validate_salesloft_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
