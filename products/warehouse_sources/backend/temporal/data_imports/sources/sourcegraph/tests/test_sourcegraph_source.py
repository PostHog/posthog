import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sourcegraph import (
    SourcegraphSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.source import SourcegraphSource


class TestSourcegraphSource:
    def setup_method(self):
        self.source = SourcegraphSource()
        self.team_id = 123
        self.config = SourcegraphSourceConfig(host="https://sourcegraph.example.com", access_token="sgp_token")

    def test_connection_host_fields_force_token_reentry_on_host_change(self):
        # `host` is where the access token is sent; changing it must re-require the
        # token so the stored secret can't be redirected to an attacker-controlled host.
        assert self.source.connection_host_fields == ["host"]

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh_only(self):
        # No Sourcegraph connection has a server-side updated-since filter; advertising
        # incremental sync would silently re-fetch everything each run.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @pytest.mark.parametrize("endpoint", ["users", "organizations"])
    def test_admin_scoped_schemas_mention_site_admin(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "site-admin" in (schemas[endpoint].description or "")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["repositories"])
        assert len(schemas) == 1
        assert schemas[0].name == "repositories"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
