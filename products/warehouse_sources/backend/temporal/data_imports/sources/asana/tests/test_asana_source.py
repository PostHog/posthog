import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.asana.source import AsanaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asana import AsanaSourceConfig


class TestAsanaSource:
    def setup_method(self):
        self.source = AsanaSource()
        self.team_id = 123
        self.config = AsanaSourceConfig(access_token="1/abc")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.asana.com/api/1.0/workspaces?limit=100",
            "403 Client Error: Forbidden for url: https://app.asana.com/api/1.0/tasks?project=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://app.asana.com/api/1.0/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_full_refresh_only(self):
        # No endpoint advertises incremental until the tasks `modified_since` filter is verified.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Asana personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.asana.source.validate_asana_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_token)
