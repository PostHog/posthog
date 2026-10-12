from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instatus import (
    InstatusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.source import InstatusSource


class TestInstatusSource:
    def setup_method(self):
        self.source = InstatusSource()
        self.team_id = 123

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(
            InstatusSourceConfig(api_key="key"), self.team_id, names=["incidents", "components"]
        )
        assert {s.name for s in schemas} == {"incidents", "components"}
