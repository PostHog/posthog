from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pendo import PendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.source import PendoSource


class TestPendoSource:
    def setup_method(self):
        self.source = PendoSource()
        self.team_id = 123
        self.config = PendoSourceConfig(integration_key="integration-key", region="eu")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["visitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "visitors"
