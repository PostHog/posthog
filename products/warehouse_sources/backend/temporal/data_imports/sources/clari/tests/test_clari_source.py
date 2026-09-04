import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.clari.source import ClariSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clari import ClariSourceConfig


class TestClariSource:
    def setup_method(self):
        self.source = ClariSource()
        self.team_id = 123
        self.config = ClariSourceConfig(api_key="key", forecast_id="fc-1")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.clari.com/v4/audit/events",
            "403 Client Error: Forbidden for url: https://api.clari.com/v4/export/jobs/123",
            "404 Client Error: Not Found for url: https://api.clari.com/v4/export/forecast/bad-id",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://api.clari.com/v4/audit/events"
        assert not any(key in error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.clari.source.validate_clari_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Clari credentials"
        mock_validate.assert_called_once_with("key")
