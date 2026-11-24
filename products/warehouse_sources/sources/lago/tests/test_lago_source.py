from products.warehouse_sources.sources.lago._config import LagoSourceConfig
from products.warehouse_sources.sources.lago.source import LagoSource


class TestLagoSource:
    def setup_method(self):
        self.source = LagoSource()
        self.team_id = 123
        self.config = LagoSourceConfig(api_key="lago_key", api_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The API key is sent to api_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["api_url"]

    def test_only_activity_logs_sync_incrementally_and_never_append(self):
        # The lookback re-reads an overlap and `from_date` is inclusive, so append would duplicate rows.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert [s.name for s in schemas if s.supports_incremental] == ["activity_logs"]
        assert not any(s.supports_append for s in schemas)
