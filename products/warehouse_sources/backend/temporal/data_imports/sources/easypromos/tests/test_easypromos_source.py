from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import (
    EASYPROMOS_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.source import EasypromosSource


class TestGetSchemas:
    def test_returns_every_endpoint(self) -> None:
        schemas = EasypromosSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_full_refresh_only(self) -> None:
        for schema in EasypromosSource().get_schemas(MagicMock(), team_id=1):
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name

    def test_should_sync_default_mirrors_settings(self) -> None:
        schemas = {s.name: s for s in EasypromosSource().get_schemas(MagicMock(), team_id=1)}
        for name, config in EASYPROMOS_ENDPOINTS.items():
            assert schemas[name].should_sync_default is config.should_sync_default

    def test_names_filter(self) -> None:
        schemas = EasypromosSource().get_schemas(MagicMock(), team_id=1, names=["promotions", "users"])
        assert {s.name for s in schemas} == {"promotions", "users"}

    def test_fan_out_description_mentions_per_promotion(self) -> None:
        schemas = {s.name: s for s in EasypromosSource().get_schemas(MagicMock(), team_id=1)}
        assert "per promotion" in (schemas["users"].description or "")
