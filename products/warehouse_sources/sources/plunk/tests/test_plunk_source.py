from products.warehouse_sources.sources.plunk._config import PlunkSourceConfig
from products.warehouse_sources.sources.plunk.source import PlunkSource


class TestPlunkSource:
    def setup_method(self):
        self.source = PlunkSource()
        self.team_id = 123
        self.config = PlunkSourceConfig(api_key="sk_test", base_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The secret key is sent to base_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["base_url"]
