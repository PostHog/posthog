from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gnews import GNewsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.source import GNewsSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gnews.source"


def _config(**overrides: Any) -> GNewsSourceConfig:
    defaults: dict[str, Any] = {"api_key": "k", "query": "posthog", "category": "general"}
    defaults.update(overrides)
    return GNewsSourceConfig(**defaults)


class TestGNewsSource:
    def setup_method(self) -> None:
        self.source = GNewsSource()

    def test_get_schemas_are_incremental_and_append_on_published_at(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}
        assert set(schemas) == {"articles", "top_headlines"}
        for schema in schemas.values():
            assert schema.supports_incremental is True
            assert schema.supports_append is True
            assert [f["field"] for f in schema.incremental_fields] == ["publishedAt"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=1, names=["top_headlines"])
        assert [s.name for s in schemas] == ["top_headlines"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert {t["name"] for t in self.source.get_documented_tables()} == {"articles", "top_headlines"}
