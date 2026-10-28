from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.settings import AVALARA_ENDPOINTS
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

    def test_fanout_endpoints_key_include_parent_identifier(self):
        # Fan-out children aggregate rows across every company, so their primary key must include
        # a company identifier unless the API documents a globally unique id (Transactions does).
        for name in _FANOUT_ENDPOINTS - {"Transactions"}:
            assert "companyId" in AVALARA_ENDPOINTS[name].primary_keys
