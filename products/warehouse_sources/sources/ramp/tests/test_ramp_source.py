from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ramp import RampSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.source import RampSource


class TestRampSource:
    def setup_method(self):
        self.source = RampSource()
        self.team_id = 123
        self.config = RampSourceConfig(environment="production", client_id="cid", client_secret="sec")

    def test_environment_is_a_connection_host_field(self):
        # Changing environment retargets where the stored client secret is sent, so it must force
        # re-entering secrets.
        assert self.source.connection_host_fields == ["environment"]
