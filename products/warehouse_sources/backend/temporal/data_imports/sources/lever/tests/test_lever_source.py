import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lever import LeverSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.source import LeverSource

INCREMENTAL_ENDPOINTS = {"opportunities"}


class TestLeverSource:
    def setup_method(self):
        self.source = LeverSource()
        self.team_id = 123
        self.config = LeverSourceConfig(api_key="test_api_key")

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.lever.co",
            "403 Client Error: Forbidden for url: https://api.lever.co",
        ],
    )
    def test_non_retryable_errors_includes_lever_key(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_non_retryable_errors_matches_observed_error_message(self):
        observed_error = "401 Client Error: Unauthorized for url: https://api.lever.co/v1/opportunities?limit=100"
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://api.clerk.com/v1/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)
