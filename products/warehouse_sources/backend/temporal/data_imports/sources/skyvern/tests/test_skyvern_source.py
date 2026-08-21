import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.skyvern import (
    SkyvernSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.source import SkyvernSource


class TestSkyvernSource:
    def setup_method(self):
        self.source = SkyvernSource()
        self.team_id = 1

    @pytest.mark.parametrize(
        "endpoint,expected_incremental,expected_primary_keys",
        [
            # Only runs has a server-side timestamp filter (created_at_start); everything else must be
            # full-refresh so the picker never offers an incremental mode that would sync nothing.
            ("runs", True, ["workflow_run_id"]),
            ("workflows", False, ["workflow_permanent_id"]),
            ("schedules", False, ["workflow_schedule_id"]),
            ("browser_profiles", False, ["browser_profile_id"]),
            ("credentials", False, ["credential_id"]),
        ],
    )
    def test_schema_sync_capabilities(self, endpoint, expected_incremental, expected_primary_keys):
        config = SkyvernSourceConfig(api_key="k")
        schemas = {s.name: s for s in self.source.get_schemas(config, self.team_id)}

        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is False
        assert schema.detected_primary_keys == expected_primary_keys
