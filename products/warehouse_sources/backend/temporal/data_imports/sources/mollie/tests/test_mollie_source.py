import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mollie import MollieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.source import MollieSource


class TestMollieSource:
    def setup_method(self):
        self.source = MollieSource()
        self.team_id = 123
        self.config = MollieSourceConfig(api_key="live_key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.mollie.com/v2/payments?limit=250",
            "403 Client Error: Forbidden for url: https://api.mollie.com/v2/settlements",
            "400 Client Error: Bad Request for url: https://api.mollie.com/v2/subscriptions?limit=250",
            "400 Client Error: Bad Request for url: https://api.mollie.com/v2/chargebacks?limit=250",
        ],
    )
    def test_non_retryable_errors_match_client_errors(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.mollie.com/v2/payments",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No Mollie list endpoint has a server-side date filter; full refresh only.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Mollie API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mollie.source.validate_mollie_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
