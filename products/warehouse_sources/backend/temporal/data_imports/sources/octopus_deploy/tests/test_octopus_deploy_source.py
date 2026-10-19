from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.octopusdeploy import (
    OctopusDeploySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octopus_deploy.source import OctopusDeploySource


class TestOctopusDeploySource:
    def setup_method(self):
        self.source = OctopusDeploySource()
        self.team_id = 123
        self.config = OctopusDeploySourceConfig(host="https://my-org.octopus.app", api_key="API-KEY")

    def test_connection_host_fields_force_key_reentry_on_host_change(self):
        # Changing host retargets the stored API key, so it must count as a host field and force
        # the editor to re-enter the key rather than silently redirecting it to a new server.
        assert self.source.connection_host_fields == ["host"]
