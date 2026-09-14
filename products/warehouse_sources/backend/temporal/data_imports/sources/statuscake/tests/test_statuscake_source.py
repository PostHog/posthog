from datetime import UTC, datetime

import pytest
from unittest import mock

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.statuscake import (
    StatuscakeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.source import StatuscakeSource

_INCREMENTAL_ENDPOINTS = {"uptime_history", "uptime_periods", "uptime_alerts", "pagespeed_history"}


class TestStatuscakeSource:
    def setup_method(self):
        self.source = StatuscakeSource()
        self.team_id = 123

    def test_source_config_is_released_alpha(self):
        config = self.source.get_source_config
        assert config.label == "StatusCake"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The scaffold shipped hidden; a finished source must be visible to users.
        assert not config.unreleasedSource

    def test_get_schemas_incremental_split(self):
        schemas = self.source.get_schemas(StatuscakeSourceConfig(api_key="token"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Only the per-test history endpoints have a server-side `after` bound; config/test lists
        # have no changed-since filter and must stay full refresh.
        assert {s.name for s in schemas if s.supports_incremental} == _INCREMENTAL_ENDPOINTS
        assert all(s.incremental_fields for s in schemas if s.supports_incremental)
        assert all(not s.incremental_fields for s in schemas if not s.supports_incremental)

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(
            StatuscakeSourceConfig(api_key="token"), self.team_id, names=["uptime_tests", "uptime_history"]
        )
        assert {s.name for s in schemas} == {"uptime_tests", "uptime_history"}

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.statuscake.com",
            "403 Client Error: Forbidden for url: https://api.statuscake.com",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

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
