from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opencorporates import (
    OpencorporatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.source import OpencorporatesSource


class TestOpencorporatesSource:
    def setup_method(self):
        self.source = OpencorporatesSource()
        self.team_id = 123
        self.config = OpencorporatesSourceConfig(api_token="token", query="acme", jurisdiction_code=None)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.opencorporates.com/v0.4/companies/search",),
            ("403 Client Error: Forbidden for url: https://api.opencorporates.com/v0.4/companies/search",),
        ]
    )
    def test_non_retryable_errors_match_auth_and_quota_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://api.opencorporates.com/v0.4/companies/search",),
            ("500 Server Error: Internal Server Error for url: https://api.opencorporates.com/v0.4/companies/search",),
            ("HTTPSConnectionPool(host='api.opencorporates.com', port=443): Read timed out.",),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)
