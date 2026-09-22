from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.source import ArgocdSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.argocd import ArgocdSourceConfig


class TestArgocdSource:
    def setup_method(self):
        self.source = ArgocdSource()
        self.team_id = 123
        self.config = ArgocdSourceConfig(host="https://argocd.example.com", api_token="tok", project=None)

    def test_get_schemas_returns_all_endpoints_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No Argo CD endpoint has a server-side timestamp filter, so nothing may advertise
        # incremental or append sync.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["applications"])
        assert [s.name for s in schemas] == ["applications"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
