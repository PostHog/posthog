from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.source import AlgunaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alguna import AlgunaSourceConfig


class TestAlgunaSource:
    def setup_method(self):
        self.source = AlgunaSource()
        self.team_id = 123
        self.config = AlgunaSourceConfig(api_key="alg-key")

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.alguna.io/customers?limit=100&offset=0",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.alguna.io/invoices?limit=100&offset=0"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("other_vendor", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("server_error", "500 Server Error for url: https://api.alguna.io/customers"),
        ]
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, _name, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No list payload carries the API's filterable date fields, so no stream can track an
        # incremental watermark — advertising incremental here would corrupt syncs.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid Alguna API key"),
        ]
    )
    def test_validate_credentials(self, _name, mock_return, expected_valid, expected_message):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.alguna.source.validate_alguna_credentials"
        ) as mock_validate:
            mock_validate.return_value = mock_return

            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

            assert is_valid is expected_valid
            assert error_message == expected_message
            mock_validate.assert_called_once_with(self.config.api_key)
