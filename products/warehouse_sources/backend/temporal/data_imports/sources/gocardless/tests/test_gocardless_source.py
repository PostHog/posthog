import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gocardless import (
    GoCardlessSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.source import GoCardlessSource


class TestGoCardlessSource:
    def setup_method(self):
        self.source = GoCardlessSource()
        self.team_id = 123
        self.config = GoCardlessSourceConfig(environment="live", access_token="access-token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.gocardless.com/customers?limit=500",
            "401 Client Error: Unauthorized for url: https://api-sandbox.gocardless.com/payments",
            "403 Client Error: Forbidden for url: https://api.gocardless.com/events",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.gocardless.com/payments",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the append-only events change log has an honest incremental;
        # mutable tables (payments, mandates) change status after creation.
        assert incremental == {"events"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid GoCardless access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.source.validate_gocardless_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("live", "access-token")
