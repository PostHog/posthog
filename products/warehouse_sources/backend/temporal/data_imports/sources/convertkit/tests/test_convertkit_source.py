from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.source import ConvertKitSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.convertkit import (
    ConvertKitSourceConfig,
)


class TestConvertKitSource:
    def setup_method(self) -> None:
        self.source = ConvertKitSource()
        self.team_id = 123
        self.config = ConvertKitSourceConfig(api_key="kit_test")

    def test_only_subscribers_supports_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["subscribers"].supports_incremental is True
        assert {f["field"] for f in schemas["subscribers"].incremental_fields} == {"created_at", "updated_at"}
        for name, schema in schemas.items():
            if name != "subscribers":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []
