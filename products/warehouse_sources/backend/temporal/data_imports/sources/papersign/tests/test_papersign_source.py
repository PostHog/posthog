from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.papersign import (
    PapersignSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.source import PapersignSource


def _config(api_token: str = "tok") -> PapersignSourceConfig:
    return PapersignSourceConfig(api_token=api_token)


class TestPapersignSchemas:
    def test_lists_all_endpoints_as_full_refresh(self) -> None:
        schemas = {s.name: s for s in PapersignSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []
            assert schema.detected_primary_keys == ["id"]
