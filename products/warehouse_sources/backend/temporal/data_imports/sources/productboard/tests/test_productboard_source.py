import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.productboard import (
    ProductboardSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.source import (
    ProductboardSource,
    _probe_path,
)


class TestProductboardSource:
    def setup_method(self):
        self.source = ProductboardSource()
        self.team_id = 123
        self.config = ProductboardSourceConfig(access_token="pb-token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.productboard.com/v2/notes",
            "403 Client Error: Forbidden for url: https://api.productboard.com/v2/entities?type[]=feature",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.productboard.com/v2/notes",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "probe_return, schema_name, expected_valid, expected_message",
        [
            ((True, 200), None, True, None),
            ((False, 401), None, False, "Invalid Productboard access token"),
            # 403 at source-create means a valid token that just lacks scope for the probe endpoint.
            ((False, 403), None, True, None),
            # 403 on a specific schema means the user can't sync that endpoint.
            ((False, 403), "notes", False, "Your access token is missing the required scope for this resource"),
            ((False, 500), None, False, "Failed to validate Productboard credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.source.validate_productboard_credentials"
    )
    def test_validate_credentials(self, mock_validate, probe_return, schema_name, expected_valid, expected_message):
        mock_validate.return_value = probe_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        assert error_message == expected_message

    @pytest.mark.parametrize(
        "schema_name, expected_path",
        [
            (None, "/members"),
            ("features", "/entities?type[]=feature"),
            ("key_results", "/entities?type[]=keyResult"),
            ("notes", "/notes"),
            ("members", "/members"),
            ("teams", "/teams"),
        ],
    )
    def test_probe_path(self, schema_name, expected_path):
        assert _probe_path(schema_name) == expected_path
