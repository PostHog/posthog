from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.settings import (
    AVALARA_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.source import AvalaraSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.avalara import (
    AvalaraSourceConfig,
)

_FANOUT_ENDPOINTS = {"Transactions", "Nexus", "Customers", "ExemptionCertificates"}


class TestAvalaraSource:
    def setup_method(self):
        self.source = AvalaraSource()
        self.team_id = 123
        self.config = AvalaraSourceConfig(account_id="12345", license_key="key", environment="production")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://rest.avatax.com/api/v2/companies",),
            ("403 Client Error: Forbidden for url: https://rest.avatax.com/api/v2/companies/1/nexus",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://rest.avatax.com/api/v2/companies",),
            ("500 Server Error: Internal Server Error for url: https://rest.avatax.com/api/v2/companies",),
            ("HTTPSConnectionPool(host='rest.avatax.com', port=443): Read timed out.",),
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

    def test_fanout_endpoints_key_include_parent_identifier(self):
        # Fan-out children aggregate rows across every company, so their primary key must include
        # a company identifier unless the API documents a globally unique id (Transactions does).
        for name in _FANOUT_ENDPOINTS - {"Transactions"}:
            assert "companyId" in AVALARA_ENDPOINTS[name].primary_keys
