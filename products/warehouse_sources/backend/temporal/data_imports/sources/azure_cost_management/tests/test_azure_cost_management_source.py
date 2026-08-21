import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.settings import (
    COST_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.source import (
    AzureCostManagementSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azurecostmanagement import (
    AzureCostManagementSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.source"

COST_ENDPOINTS = ("cost_by_service", "cost_by_resource_group", "cost_by_resource", "amortized_cost_by_service")


class TestAzureCostManagementSource:
    def setup_method(self) -> None:
        self.source = AzureCostManagementSource()
        self.config = AzureCostManagementSourceConfig(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            scope="subscriptions/abc",
            start_date=None,
        )

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("2025-03-01", "2026-06-01")
        # New sources start on the newest stable version; existing pins are unaffected.
        assert self.source.default_version == "2026-06-01"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize("endpoint", COST_ENDPOINTS)
    def test_cost_endpoints_sync_incrementally_on_the_usage_date(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["usage_date"]
        # Azure restates recent days, so each run re-reads a trailing window.
        assert schema.default_incremental_lookback_seconds == COST_LOOKBACK_SECONDS
