import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tailscale import (
    TailscaleAuthMethodConfig,
    TailscaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.settings import ENDPOINTS
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

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, supports_append",
        [
            ("devices", False),
            ("users", False),
            ("keys", False),
            ("configuration_audit_logs", True),
        ],
    )
    def test_schema_sync_support(self, endpoint, supports_append):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        # Audit log records have no unique id, so merge-based incremental syncs must never
        # be offered — the time filter powers append syncs only.
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is supports_append
        assert bool(schemas[endpoint].incremental_fields) is supports_append

    def test_audit_logs_schema_mentions_retention(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "90 days" in (schemas["configuration_audit_logs"].description or "")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["devices"])
        assert [s.name for s in schemas] == ["devices"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
