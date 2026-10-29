from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.source import FusionAuthSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fusionauth import (
    FusionAuthSourceConfig,
)


class TestFusionAuthSource:
    def setup_method(self):
        self.source = FusionAuthSource()
        self.team_id = 123
        self.config = FusionAuthSourceConfig(base_url="https://auth.example.com", api_key="00token")

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["base_url"]
