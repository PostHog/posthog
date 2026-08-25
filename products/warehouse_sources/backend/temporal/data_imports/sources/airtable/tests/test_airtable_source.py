import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source import AirtableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airtable import (
    AirtableSourceConfig,
)


class TestAirtableSource:
    def setup_method(self):
        self.source = AirtableSource()
        self.team_id = 123
        self.config = AirtableSourceConfig(personal_access_token="pat-token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.airtable.com/v0/meta/bases",
            "403 Client Error: Forbidden for url: https://api.airtable.com/v0/app1/tbl1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.airtable.com/v0/meta/bases",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only records can be filtered server-side (CREATED_TIME() formula).
        assert incremental == {"records"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (
                False,
                False,
                "Invalid Airtable personal access token. Check that the token is correct and has access to the bases you want to sync, then try again.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airtable.source.validate_airtable_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.personal_access_token)
