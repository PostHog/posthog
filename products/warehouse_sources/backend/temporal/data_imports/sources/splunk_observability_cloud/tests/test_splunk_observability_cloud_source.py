from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.splunkobservabilitycloud import (
    SplunkObservabilityCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.settings import (
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.source import (
    SplunkObservabilityCloudSource,
)


class TestSplunkObservabilityCloudSource:
    def setup_method(self) -> None:
        self.source = SplunkObservabilityCloudSource()
        self.team_id = 123
        self.config = SplunkObservabilityCloudSourceConfig(realm="us0", access_token="test-token")

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
