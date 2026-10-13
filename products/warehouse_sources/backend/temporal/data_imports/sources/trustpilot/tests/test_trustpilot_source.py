from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trustpilot import (
    TrustPilotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.source import TrustPilotSource


class TestTrustPilotSource:
    def setup_method(self):
        self.source = TrustPilotSource()
        self.team_id = 123
        self.config = TrustPilotSourceConfig(api_key="key", api_secret="secret", business_unit="example.com")

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.trustpilot.com/v1/private/business-units/x/reviews",
            "403 Client Error: Forbidden for url: https://api.trustpilot.com/v1/private/product-reviews/business-units/x/reviews",
            "404 Client Error: Not Found for url: https://api.trustpilot.com/v1/business-units/x",
            "No Trustpilot business unit found for 'example.com'. Enter your domain exactly as it appears.",
            "Trustpilot rejected the API key (HTTP 401). Check the API key in your Trustpilot Business account.",
            "invalid_client from the OAuth2 token endpoint [oauth2_token_config_error]",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            "429 Client Error: Too Many Requests for url: https://api.trustpilot.com/v1/business-units/x/reviews",
            "500 Server Error: Internal Server Error for url: https://api.trustpilot.com/v1/business-units/x",
            "HTTP 503 from the OAuth2 token endpoint",
            "HTTPSConnectionPool(host='api.trustpilot.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
