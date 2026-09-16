from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.statuspage import (
    StatuspageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.source import StatuspageSource


class TestStatuspageSource:
    def setup_method(self):
        self.source = StatuspageSource()
        self.team_id = 123

    def test_get_schemas_returns_all_endpoints_as_full_refresh(self):
        schemas = self.source.get_schemas(StatuspageSourceConfig(api_key="key"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No server-side timestamp filter exists, so every schema is full-refresh only.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)
