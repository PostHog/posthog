from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tailscale import (
    TailscaleAuthMethodConfig,
    TailscaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.source import TailscaleSource


class TestTailscaleSource:
    def setup_method(self):
        self.source = TailscaleSource()
        self.team_id = 123
        self.config = TailscaleSourceConfig(
            auth_method=TailscaleAuthMethodConfig(selection="api_key", api_key="tskey-api-test"),
            tailnet="example.com",
        )

    def test_tailnet_change_requires_reentering_secrets(self):
        # The update serializer keys off this to force re-entry of the stored credential
        # when the tailnet is retargeted.
        assert self.source.connection_host_fields == ["tailnet"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["devices"])
        assert [s.name for s in schemas] == ["devices"]
