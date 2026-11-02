import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hibob import HiBobSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.source import HiBobSource


class TestHiBobSource:
    def setup_method(self):
        self.source = HiBobSource()
        self.team_id = 123
        self.config = HiBobSourceConfig(service_user_id="service-id", service_user_token="service-token")

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)
