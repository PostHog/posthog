from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import ENDPOINTS
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

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No Algolia endpoint exposes a server-side updated-since filter, so every schema is
        # full refresh only.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)
