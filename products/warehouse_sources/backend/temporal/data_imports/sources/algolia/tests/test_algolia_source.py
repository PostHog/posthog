from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import (
    ALGOLIA_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.source import AlgoliaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.algolia import (
    AlgoliaSourceConfig,
)


class TestAlgoliaSource:
    def setup_method(self) -> None:
        self.source = AlgoliaSource()
        self.team_id = 123
        self.config = AlgoliaSourceConfig(application_id="APPID", api_key="test-key", index_name="my_index")

    def test_application_id_is_a_connection_host_field(self) -> None:
        # The stored API key is sent to the host derived from application_id, so changing
        # it must force the key to be re-entered.
        assert self.source.connection_host_fields == ["application_id"]

    def test_incremental_endpoints_declare_a_server_side_date_filter(self) -> None:
        # An endpoint that advertises incremental sync without a `startDate` to bind the cursor
        # to would re-read its whole period every run while reporting itself as incremental.
        for name, config in ALGOLIA_ENDPOINTS.items():
            assert bool(config.incremental_fields) == (config.start_param is not None), name

    def test_get_schemas_offers_merge_but_never_append(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Each sync re-reads a trailing window, so appending would store each day twice.
        assert all(not schema.supports_append for schema in schemas.values())
        assert schemas["conversion_rate"].supports_incremental
        assert [f["field"] for f in schemas["conversion_rate"].incremental_fields] == ["date"]
        assert not schemas["records"].supports_incremental
        assert not schemas["top_filters"].supports_incremental
