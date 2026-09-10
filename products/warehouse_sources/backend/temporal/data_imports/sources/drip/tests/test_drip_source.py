from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.source import DripSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.drip import DripSourceConfig


class TestDripSource:
    def setup_method(self):
        self.source = DripSource()
        self.team_id = 123
        self.config = DripSourceConfig(api_token="test_token", account_id="9999999")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Drip exposes no reliable server-side update cursor, so everything is full refresh.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.getdrip.com/v2/9999/subscribers"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.getdrip.com/v2/9999/campaigns"),
        ]
    )
    def test_non_retryable_errors_match_drip(self, _name, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("stripe", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("klaviyo", "403 Client Error: Forbidden for url: https://a.klaviyo.com/api/profiles"),
        ]
    )
    def test_non_retryable_errors_do_not_match_other_vendors(self, _name, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable)
