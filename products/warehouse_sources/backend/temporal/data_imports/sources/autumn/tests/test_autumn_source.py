from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.autumn.source import AutumnSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.autumn import AutumnSourceConfig


class TestAutumnSource:
    def setup_method(self) -> None:
        self.source = AutumnSource()
        self.config = AutumnSourceConfig(api_key="am_sk_test")

    def test_get_schemas_advertises_incremental_only_for_events(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=123)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)

        by_name = {schema.name: schema for schema in schemas}
        incremental_names = [name for name, schema in by_name.items() if schema.supports_incremental]
        assert incremental_names == ["Events"]
        assert [field["field"] for field in by_name["Events"].incremental_fields] == ["timestamp"]
