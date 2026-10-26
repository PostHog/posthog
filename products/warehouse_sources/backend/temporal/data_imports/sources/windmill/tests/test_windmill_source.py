from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.windmill import (
    WindmillSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.source import WindmillSource

BASE_URL = "https://app.windmill.dev"
WORKSPACE = "my-workspace"


class TestWindmillSource:
    def setup_method(self):
        self.source = WindmillSource()
        self.team_id = 123
        self.config = WindmillSourceConfig(host=BASE_URL, workspace=WORKSPACE, api_token="token")

    def test_connection_host_fields_force_token_reentry_on_host_change(self):
        # host receives the api_token, so editing it must re-require the token (no exfiltration
        # of the stored bearer token to an attacker-controlled host).
        assert self.source.connection_host_fields == ["host"]
