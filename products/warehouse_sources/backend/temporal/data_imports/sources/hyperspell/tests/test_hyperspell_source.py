from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hyperspell import (
    HyperspellSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.source import HyperspellSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.source"


class TestHyperspellSource:
    def setup_method(self):
        self.source = HyperspellSource()
        self.team_id = 123
        self.config = HyperspellSourceConfig(api_key="hs_test", region="eu", user_ids="user-1, user-2")

    def test_get_schemas_lists_all_endpoints_as_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No Hyperspell endpoint has a server-side timestamp filter, so nothing may
        # advertise incremental support.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["memories", "nonexistent"])

        assert [schema.name for schema in schemas] == ["memories"]
