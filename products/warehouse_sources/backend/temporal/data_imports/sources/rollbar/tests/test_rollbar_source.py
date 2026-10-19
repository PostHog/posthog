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
        "observed_error",
        [
            "HTTPSConnectionPool(host='api.rollbar.com', port=443): Max retries exceeded with "
            'url: /api/1/instances?limit=1000 (Caused by ReadTimeoutError("HTTPSConnectionPool'
            "(host='api.rollbar.com', port=443): Read timed out. (read timeout=60)\"))",
            "Rollbar API error (retryable): status=503, url=https://api.rollbar.com/api/1/items?page=1",
        ],
    )
    def test_retryable_errors_match_exhausted_retry(self, observed_error):
        retryable_errors = self.source.get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Rollbar rejected your access token."), False, "Rollbar rejected your access token."),
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
