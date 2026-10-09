from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.signoz import SigNozSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.source import SigNozSource


class TestSigNozSource:
    def setup_method(self) -> None:
        self.source = SigNozSource()
        self.team_id = 123
        self.config = SigNozSourceConfig(host="example.signoz.io", api_key="signoz-key")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["traces"])
        assert len(schemas) == 1
        assert schemas[0].name == "traces"
