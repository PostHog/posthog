import pytest

from products.warehouse_sources.sources.sourcegraph._config import SourcegraphSourceConfig
from products.warehouse_sources.sources.sourcegraph.settings import ENDPOINTS
from products.warehouse_sources.sources.sourcegraph.source import SourcegraphSource


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

    def test_only_endpoints_that_can_skip_synced_rows_offer_incremental_sync(self):
        # Most connections have no server-side filter; advertising incremental sync there would
        # silently re-fetch everything each run.
        incremental = {s.name for s in self.source.get_schemas(self.config, self.team_id) if s.supports_incremental}
        assert incremental == {"commits", "exported_events"}

    @pytest.mark.parametrize("endpoint", ["users", "organizations"])
    def test_admin_scoped_schemas_mention_site_admin(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "site-admin" in (schemas[endpoint].description or "")
