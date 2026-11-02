from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.helicone import (
    HeliconeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.settings import REQUESTS_ENDPOINT
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source import HeliconeSource


class TestHeliconeSource:
    def setup_method(self):
        self.source = HeliconeSource()
        self.team_id = 123
        self.config = HeliconeSourceConfig(api_key="sk-helicone-key", region="us")

    def test_region_is_a_connection_host_field(self):
        # Changing the regional host must force re-entry of the API key (credential retargeting guard).
        assert self.source.connection_host_fields == ["region"]

    def test_source_for_pipeline_drops_last_value_on_full_refresh(self):
        result = SourceDriver(self.source, self.config).run(
            REQUESTS_ENDPOINT,
            [ScriptedResponse(json={"data": [], "error": None})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        # When the user isn't running incrementally, no watermark should leak through.
        assert result.raised is None
        assert result.requests[0].json()["filter"] == "all"
