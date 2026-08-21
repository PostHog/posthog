from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spacelift import (
    SpaceliftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.settings import INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source import SpaceliftSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source"


class TestSpaceliftSource:
    def setup_method(self):
        self.source = SpaceliftSource()
        self.team_id = 123
        self.config = SpaceliftSourceConfig(account_name="my-company", api_key_id="key-id", api_key_secret="key-secret")

    def test_only_runs_supports_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["runs"].supports_incremental is True
        assert [f["field"] for f in schemas["runs"].incremental_fields] == ["createdAt"]
        assert schemas["runs"].incremental_fields == INCREMENTAL_FIELDS["runs"]
        for name, schema in schemas.items():
            # Incremental re-pulls a lookback window that only merge dedupes.
            assert schema.supports_append is False
            if name != "runs":
                assert schema.supports_incremental is False
