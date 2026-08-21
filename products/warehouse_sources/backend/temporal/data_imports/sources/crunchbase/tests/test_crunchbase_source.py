import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source import CrunchbaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crunchbase import (
    CrunchbaseSourceConfig,
)


class TestCrunchbaseSource:
    def setup_method(self):
        self.source = CrunchbaseSource()
        self.team_id = 123
        self.config = CrunchbaseSourceConfig(api_key="user-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.crunchbase.com/v4/data/searches/organizations",
            "403 Client Error: Forbidden for url: https://api.crunchbase.com/v4/data/searches/people",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.crunchbase.com/v4/data/searches/organizations",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every collection search supports the updated_at gte predicate.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source.validate_crunchbase_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "Enterprise/Applications" in (error_message or "")
        mock_validate.assert_called_once_with(self.config.api_key)
