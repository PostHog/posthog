from datetime import UTC, datetime

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.statuscake import (
    StatuscakeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.source import StatuscakeSource


class TestStatuscakeSource:
    def setup_method(self):
        self.source = StatuscakeSource()
        self.team_id = 123

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.source.statuscake_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_statuscake_source):
        # A full refresh must not carry a stale watermark into the transport, or the sync would
        # silently skip history older than the last incremental run.
        inputs = mock.MagicMock()
        inputs.schema_name = "uptime_history"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = datetime(2026, 1, 1, tzinfo=UTC)

        self.source.source_for_pipeline(StatuscakeSourceConfig(api_key="token"), mock.MagicMock(), inputs)

        assert mock_statuscake_source.call_args.kwargs["db_incremental_field_last_value"] is None
