from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.orca_security.source import OrcaSecuritySource


class TestOrcaSecuritySource:
    def setup_method(self):
        self.source = OrcaSecuritySource()
        self.team_id = 42

    def test_region_change_requires_credential_reentry(self):
        # `region` retargets where the stored token is sent, so editing it must force re-entering
        # the token — dropping this would let an editor redirect the preserved credential.
        assert self.source.connection_host_fields == ["region"]

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so public docs may render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filters_by_name(self):
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id, names=["alerts"])
        assert [s.name for s in schemas] == ["alerts"]
