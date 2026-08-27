from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gerrit import GerritSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.source import GerritSource


class TestGerritSource:
    def setup_method(self):
        self.source = GerritSource()
        self.team_id = 123
        self.config = GerritSourceConfig(host="https://gerrit.example.com", username="bot", http_password="secret")

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_changes_supports_incremental(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["changes"].supports_incremental is True
        assert [f["field"] for f in schemas["changes"].incremental_fields] == ["updated"]
        for name in ("accounts", "projects", "groups"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["changes"])
        assert [s.name for s in schemas] == ["changes"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self):
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables.keys()) == set(ENDPOINTS)
        assert "Incremental" in tables["changes"]["sync_methods"]
        assert tables["changes"]["description"]
