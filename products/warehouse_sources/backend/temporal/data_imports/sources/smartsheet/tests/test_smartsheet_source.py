import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartsheet import (
    SmartsheetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.source import SmartsheetSource


class TestSmartsheetSource:
    def setup_method(self):
        self.source = SmartsheetSource()
        self.team_id = 123
        self.config = SmartsheetSourceConfig(access_token="token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.smartsheet.com/2.0/sheets?page=1&pageSize=100",
            "403 Client Error: Forbidden for url: https://api.smartsheet.com/2.0/users",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.smartsheet.com/2.0/sheets",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh(self):
        # No Smartsheet list endpoint exposes an order-stable server-side timestamp filter,
        # so every schema ships as full refresh.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == INCREMENTAL_FIELDS[schema.name]
            assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Smartsheet access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.source.validate_smartsheet_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_token)
