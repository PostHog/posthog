from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.source import ClerkSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clerk import ClerkSourceConfig


class TestClerkSource:
    def setup_method(self):
        self.source = ClerkSource()
        self.team_id = 123
        self.config = ClerkSourceConfig(secret_key="sk_live_test")

    def test_get_schemas_filtered_by_names(self):
        first_endpoint = next(iter(ENDPOINTS))
        schemas = self.source.get_schemas(self.config, self.team_id, names=[first_endpoint])

        assert len(schemas) == 1
        assert schemas[0].name == first_endpoint
