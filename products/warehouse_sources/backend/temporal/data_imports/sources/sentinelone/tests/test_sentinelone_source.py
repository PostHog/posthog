from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sentinelone import (
    SentineloneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.source import SentineloneSource


class TestSentineloneSource:
    def setup_method(self):
        self.source = SentineloneSource()
        self.team_id = 123
        self.config = SentineloneSourceConfig(console_url="example.sentinelone.net", api_token="tok")

    def test_console_url_is_a_connection_host_field(self):
        # Retargeting the console URL must force re-entry of the API token — otherwise a
        # member could point the stored token at a server they control.
        assert self.source.connection_host_fields == ["console_url"]
