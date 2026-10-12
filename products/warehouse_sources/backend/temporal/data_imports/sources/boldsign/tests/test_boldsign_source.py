from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.source import BoldSignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.boldsign import (
    BoldSignSourceConfig,
)


class TestBoldSignSource:
    def setup_method(self):
        self.source = BoldSignSource()
        self.team_id = 123
        self.config = BoldSignSourceConfig(api_key="key", region="us")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog (no I/O) so the public docs can render Supported tables.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["documents"])
        assert len(schemas) == 1
        assert schemas[0].name == "documents"
