import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hatchet import (
    HatchetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.source import HatchetSource


class TestHatchetSource:
    def setup_method(self):
        self.source = HatchetSource()
        self.team_id = 123
        self.config = HatchetSourceConfig(api_token="tok", host=None, tenant_id=None)

    @pytest.mark.parametrize(
        "endpoint,expected_incremental,expected_primary_keys",
        [
            ("workflow_runs", True, ["id"]),
            ("tasks", True, ["id"]),
            ("events", True, ["id"]),
            ("event_keys", False, ["key"]),
        ],
    )
    def test_get_schemas(self, endpoint, expected_incremental, expected_primary_keys):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        assert schema.detected_primary_keys == expected_primary_keys
