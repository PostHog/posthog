from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.transistor import (
    TransistorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.settings import (
    ENDPOINTS,
    TRANSISTOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.source import TransistorSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.transistor.source"


class TestTransistorSource:
    def setup_method(self):
        self.source = TransistorSource()
        self.config = TransistorSourceConfig(api_key="secret-key")

    def test_get_schemas_matches_the_endpoint_catalog(self):
        schemas = self.source.get_schemas(self.config, team_id=123)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        for schema in schemas:
            endpoint = TRANSISTOR_ENDPOINTS[schema.name]
            assert schema.detected_primary_keys == endpoint.primary_keys
            assert schema.supports_incremental is endpoint.supports_incremental

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            # Every primary key column needs a description, since those are the join keys the
            # agent reasons about.
            assert set(TRANSISTOR_ENDPOINTS[endpoint].primary_keys) <= set(entry.get("columns", {}))
