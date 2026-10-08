from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gong import GongSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.source import GongSource


class TestGongSource:
    def setup_method(self):
        self.source = GongSource()
        self.team_id = 123
        self.config = GongSourceConfig(access_key="key", access_key_secret="secret")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])

        assert len(schemas) == 1
        assert schemas[0].name == "calls"
