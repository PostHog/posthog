import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.source import ApolloSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.apollo import ApolloSourceConfig


class TestApolloSource:
    def setup_method(self):
        self.source = ApolloSource()
        self.team_id = 123
        self.config = ApolloSourceConfig(api_key="api-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.apollo.io/api/v1/contacts/search",
            "403 Client Error: Forbidden for url: https://api.apollo.io/api/v1/accounts/search",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.apollo.io/api/v1/contacts/search",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Contacts and accounts support sort-based CDC; opportunities don't.
        assert incremental == {"contacts", "accounts"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Apollo rejected this API key. Create a key in Apollo under Settings > Integrations > API. "
                "API access requires a paid Apollo plan.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.apollo.source.validate_apollo_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
