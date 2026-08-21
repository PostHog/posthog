from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.source import OrcaSecuritySource


class TestOrcaSecuritySource:
    def setup_method(self):
        self.source = OrcaSecuritySource()
        self.team_id = 42

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_alerts_is_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(mock.MagicMock(), self.team_id)}
        assert schemas["alerts"].supports_incremental is True
        assert [f["field"] for f in schemas["alerts"].incremental_fields] == ["CreatedAt"]
        for name in ("assets", "cloud_accounts", "vulnerabilities"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filters_by_name(self):
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id, names=["alerts"])
        assert [s.name for s in schemas] == ["alerts"]
