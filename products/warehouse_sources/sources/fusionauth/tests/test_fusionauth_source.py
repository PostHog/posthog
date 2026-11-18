from products.warehouse_sources.sources.fusionauth._config import FusionAuthSourceConfig
from products.warehouse_sources.sources.fusionauth.source import FusionAuthSource


class TestFusionAuthSource:
    def setup_method(self):
        self.source = FusionAuthSource()
        self.team_id = 123
        self.config = FusionAuthSourceConfig(base_url="https://auth.example.com", api_key="00token")

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["base_url"]
