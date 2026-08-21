import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wasabi import WasabiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.settings import (
    UTILIZATION_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.source import WasabiSource


class TestWasabiSource:
    def setup_method(self) -> None:
        self.source = WasabiSource()
        self.team_id = 123
        self.config = WasabiSourceConfig(api_key="wasabi-key")

    @pytest.mark.parametrize("endpoint", ["utilizations", "bucket_utilizations"])
    def test_get_schemas_incremental_endpoints_are_merge_only(self, endpoint: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is True
        # The date-window walk re-reads a boundary day each run, so append would duplicate rows.
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == ["StartTime"]
        assert schema.default_incremental_lookback_seconds == UTILIZATION_LOOKBACK_SECONDS
