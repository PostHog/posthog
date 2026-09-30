import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.source import AmplemarketSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplemarket import (
    AmplemarketSourceConfig,
)


class TestAmplemarketSource:
    def setup_method(self):
        self.source = AmplemarketSource()
        self.team_id = 123
        self.config = AmplemarketSourceConfig(api_key="api-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.amplemarket.com/sequences",
            "403 Client Error: Forbidden for url: https://api.amplemarket.com/calls?page[size]=20",
        ],
    )
    def test_non_retryable_errors_match_amplemarket_client_errors(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "429 Client Error: Too Many Requests for url: https://api.amplemarket.com/people/search",
            "500 Server Error for url: https://api.amplemarket.com/sequences",
        ],
    )
    def test_non_retryable_errors_does_not_match_retryable_or_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_ships_every_endpoint_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No endpoint has a verified server-side timestamp filter, so none may advertise
        # incremental sync (see settings.py).
        assert not any(schema.supports_incremental for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Amplemarket API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.source.validate_amplemarket_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
