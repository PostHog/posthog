from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instatus import (
    InstatusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.source import InstatusSource


class TestInstatusSource:
    def setup_method(self):
        self.source = InstatusSource()
        self.team_id = 123

    def test_get_schemas_returns_all_endpoints_as_full_refresh(self):
        schemas = self.source.get_schemas(InstatusSourceConfig(api_key="key"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No server-side timestamp filter exists, so every schema is full-refresh only.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(
            InstatusSourceConfig(api_key="key"), self.team_id, names=["incidents", "components"]
        )
        assert {s.name for s in schemas} == {"incidents", "components"}

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — the docs Supported tables section renders from it.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
