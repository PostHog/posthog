from typing import Any

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.splunkobservabilitycloud import (
    SplunkObservabilityCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.settings import (
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.source import (
    SplunkObservabilityCloudSource,
)


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "detectors",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSplunkObservabilityCloudSource:
    def setup_method(self) -> None:
        self.source = SplunkObservabilityCloudSource()
        self.team_id = 123
        self.config = SplunkObservabilityCloudSourceConfig(realm="us0", access_token="test-token")

    def test_realm_is_a_connection_host_field(self) -> None:
        # The realm becomes the request hostname the stored token is sent to, so
        # changing it must force the token to be re-entered.
        assert self.source.connection_host_fields == ["realm"]

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the two endpoints with a server-side time filter (detector events'
        # from/to, SignalFlow's start/stop) advertise incremental sync.
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        assert incremental == {"detector_events", "metric_time_series"}
        for name in incremental:
            assert [f["field"] for f in schemas[name].incremental_fields] == ["timestamp"]

    def test_get_schemas_default_sync_selection(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # dimensions (unbounded volume) and metric_time_series (needs the optional
        # SignalFlow program) must not be force-enabled by one-shot setup.
        off_by_default = {name for name, s in schemas.items() if not s.should_sync_default}
        assert off_by_default == {"dimensions", "metric_time_series"}

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["detectors"])
        assert [s.name for s in schemas] == ["detectors"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_canonical_descriptions_cover_known_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Keyed by endpoint name: an entry for a non-existent endpoint silently never
        # applies, and a missing entry falls back to paid LLM enrichment.
        assert set(descriptions) == set(ENDPOINTS)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.source.splunk_observability_cloud_source"
    )
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A leftover watermark from a previous incremental config must not narrow a
        # full-refresh run.
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2026-01-01")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
