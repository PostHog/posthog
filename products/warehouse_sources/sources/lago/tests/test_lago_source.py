from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lago import LagoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.source import LagoSource


class TestLagoSource:
    def setup_method(self):
        self.source = LagoSource()
        self.team_id = 123
        self.config = LagoSourceConfig(api_key="lago_key", api_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The API key is sent to api_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["api_url"]

    def test_all_schemas_are_full_refresh(self):
        # Lago exposes no universal server-side cursor, so every stream ships full-refresh only.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)
