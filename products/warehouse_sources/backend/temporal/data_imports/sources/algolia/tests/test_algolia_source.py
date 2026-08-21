from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import ALGOLIA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.source import AlgoliaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.algolia import (
    AlgoliaSourceConfig,
)


class TestAlgoliaSource:
    def setup_method(self) -> None:
        self.source = AlgoliaSource()
        self.team_id = 123
        self.config = AlgoliaSourceConfig(application_id="APPID", api_key="test-key", index_name="my_index")

    def test_get_schemas_should_sync_defaults_match_settings(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name, endpoint in ALGOLIA_ENDPOINTS.items():
            assert schemas[name].should_sync_default == endpoint.should_sync_default
