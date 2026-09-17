import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.settings import ENDPOINTS
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

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("Users", False),
            ("AuditLogs", True),
            ("EventLogs", True),
            ("LoginRecords", True),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_users_schema_has_window_cap_description(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "10,000" in (schemas["Users"].description or "")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Users"])
        assert len(schemas) == 1
        assert schemas[0].name == "Users"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
