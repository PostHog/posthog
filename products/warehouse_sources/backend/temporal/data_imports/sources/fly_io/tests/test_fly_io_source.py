from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.source import FlyIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flyio import FlyIoSourceConfig


def _config() -> FlyIoSourceConfig:
    return FlyIoSourceConfig(api_token="FlyV1 secret", organization_slug="acme")


class TestGetSchemas:
    def test_returns_all_endpoints_full_refresh(self) -> None:
        schemas = {s.name: s for s in FlyIoSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS) == {"apps", "machines", "volumes"}
        # No verified server-side time filter, so every stream is full refresh only.
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.detected_primary_keys == ["id"]
