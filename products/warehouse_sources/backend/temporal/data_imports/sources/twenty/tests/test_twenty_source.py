from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twenty import TwentySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.source import TwentySource


class TestTwentySource:
    def setup_method(self):
        self.source = TwentySource()
        self.team_id = 123
        self.config = TwentySourceConfig(api_key="tok", base_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The API key is sent to base_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["base_url"]
