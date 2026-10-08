from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.skyvern import (
    SkyvernSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.source import SkyvernSource


class TestSkyvernSource:
    def setup_method(self):
        self.source = SkyvernSource()
        self.team_id = 1

    def test_get_schemas_can_filter_by_name(self):
        config = SkyvernSourceConfig(api_key="k")
        schemas = self.source.get_schemas(config, self.team_id, names=["runs"])
        assert [s.name for s in schemas] == ["runs"]

    def test_base_url_is_a_connection_host_field(self):
        # base_url decides where the API key is sent, so retargeting it must re-require the secret —
        # otherwise the stored key could be exfiltrated to an attacker-controlled host on edit.
        assert self.source.connection_host_fields == ["base_url"]
