from unittest import mock

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.source import OrcaSecuritySource


class TestOrcaSecuritySource:
    def setup_method(self):
        self.source = OrcaSecuritySource()
        self.team_id = 42

    def test_source_is_released(self):
        # A finished source must be visible: no unreleasedSource flag, soft ALPHA label.
        config = self.source.get_source_config
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_region_change_requires_credential_reentry(self):
        # `region` retargets where the stored token is sent, so editing it must force re-entering
        # the token — dropping this would let an editor redirect the preserved credential.
        assert self.source.connection_host_fields == ["region"]

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so public docs may render the table list.
        assert self.source.lists_tables_without_credentials is True

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

    def test_non_retryable_errors_cover_auth(self):
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error: Unauthorized" in errors
        assert "403 Client Error: Forbidden" in errors
