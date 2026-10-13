from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okta import OktaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.source import OktaSource


class TestOktaSource:
    def setup_method(self):
        self.source = OktaSource()
        self.team_id = 123
        self.config = OktaSourceConfig(okta_domain="example.okta.com", api_key="00token")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert len(schemas) == 1
        assert schemas[0].name == "users"
