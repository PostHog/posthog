import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.settings import ENDPOINTS
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

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental, append",
        [
            ("authentication_logs", True, False),
            # No unique event id: merging would multi-match, so the admin log is append-only.
            ("administrator_logs", False, True),
            ("telephony_logs", True, False),
            ("activity_logs", True, False),
            ("users", False, False),
            ("groups", False, False),
            ("phones", False, False),
            ("admins", False, False),
            ("integrations", False, False),
        ],
    )
    def test_schema_sync_modes(self, endpoint, incremental, append):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is append

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users", "nope"])
        assert [s.name for s in schemas] == ["users"]
