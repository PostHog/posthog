from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.source import CratesIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cratesio import (
    CratesIOSourceConfig,
)


class TestCratesIOSource:
    def setup_method(self):
        self.source = CratesIOSource()
        self.team_id = 123
        self.config = CratesIOSourceConfig(crates="serde\ntokio")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["versions"])

        assert [schema.name for schema in schemas] == ["versions"]
