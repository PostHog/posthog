import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.quo import QuoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.source import QuoSource


class TestQuoSource:
    def setup_method(self):
        self.source = QuoSource()
        self.team_id = 123
        self.config = QuoSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.quo.com/v1/conversations?maxResults=100",
            "403 Client Error: Forbidden for url: https://api.quo.com/v1/calls?phoneNumberId=PN1",
        ],
    )
    def test_non_retryable_errors_match_quo_client_errors(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.quo.com/v1/calls",
            "429 Client Error: Too Many Requests for url: https://api.quo.com/v1/messages",
        ],
    )
    def test_non_retryable_errors_do_not_match_retryable_or_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Quo API key"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.quo.source.validate_quo_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
