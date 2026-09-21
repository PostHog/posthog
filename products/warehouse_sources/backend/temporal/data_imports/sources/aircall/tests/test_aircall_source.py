import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.source import AircallSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aircall import (
    AircallSourceConfig,
)


class TestAircallSource:
    def setup_method(self):
        self.source = AircallSource()
        self.team_id = 123
        self.config = AircallSourceConfig(api_id="api-id", api_token="api-token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.aircall.io/v1/calls?per_page=50",
            "403 Client Error: Forbidden for url: https://api.aircall.io/v1/contacts",
            "400 Client Error: Bad Request for url: https://api.aircall.io/v1/contacts?per_page=50&page=201",
        ],
    )
    def test_non_retryable_errors_match_aircall_client_errors(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.aircall.io/v1/calls",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        by_name = {schema.name for schema in schemas if schema.supports_incremental}
        # Only calls and contacts expose Aircall's server-side `from` timestamp filter.
        assert by_name == {"calls", "contacts"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Aircall API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.aircall.source.validate_aircall_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_id, self.config.api_token)
