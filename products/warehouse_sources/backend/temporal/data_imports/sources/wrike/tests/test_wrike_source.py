from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wrike import WrikeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.source import WrikeSource


class TestWrikeSource:
    def setup_method(self):
        self.source = WrikeSource()
        self.team_id = 123
        self.config = WrikeSourceConfig(access_token="token", host="www.wrike.com")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tasks"])
        assert len(schemas) == 1
        assert schemas[0].name == "tasks"
