from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gerrit import GerritSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.source import GerritSource


class TestGerritSource:
    def setup_method(self):
        self.source = GerritSource()
        self.team_id = 123
        self.config = GerritSourceConfig(host="https://gerrit.example.com", username="bot", http_password="secret")

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True
