from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.source import BreezometerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.breezometer import (
    BreezometerSourceConfig,
)


class TestBreezometerSource:
    def setup_method(self):
        self.source = BreezometerSource()
        self.team_id = 123
        self.config = BreezometerSourceConfig(api_key="test-key", locations="51.5,-0.12,London")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — must opt in so public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["pollen_forecast"])

        assert [schema.name for schema in schemas] == ["pollen_forecast"]
