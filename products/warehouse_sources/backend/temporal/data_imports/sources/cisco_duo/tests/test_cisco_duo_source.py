from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.source import CiscoDuoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ciscoduo import (
    CiscoDuoSourceConfig,
)


class TestCiscoDuoSource:
    def setup_method(self):
        self.source = CiscoDuoSource()
        self.team_id = 123
        self.config = CiscoDuoSourceConfig(
            api_hostname="api-xxxxxxxx.duosecurity.com",
            integration_key="DIWJ8X6AEYOR5OMC6TQ1",
            secret_key="secret",
        )

    def test_connection_host_fields_covers_api_hostname(self):
        # Retargeting api_hostname must re-require the secret key, or a member could point
        # the stored credential at a host they control.
        assert self.source.connection_host_fields == ["api_hostname"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users", "nope"])
        assert [s.name for s in schemas] == ["users"]
