from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gorgias import (
    GorgiasSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.settings import (
    ENDPOINTS,
    GORGIAS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.source import GorgiasSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.source"


def _config() -> GorgiasSourceConfig:
    return GorgiasSourceConfig(gorgias_domain="acme", email="you@acme.com", api_key="key")


class TestGorgiasSource:
    def test_get_schemas_marks_incremental_per_endpoint(self) -> None:
        schemas = {s.name: s for s in GorgiasSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        # Incremental support mirrors the endpoint catalog: mutable/append-only resources
        # are incremental-capable, mutable config tables stay full-refresh.
        assert {name: s.supports_incremental for name, s in schemas.items()} == {
            name: GORGIAS_ENDPOINTS[name].supports_incremental for name in ENDPOINTS
        }
        assert schemas["tickets"].supports_incremental is True
        assert schemas["tags"].supports_incremental is False
        assert all(s.supports_append is False for s in schemas.values())
