from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gleif import GleifSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source import GleifSource


class TestGleifSource:
    def setup_method(self) -> None:
        self.source = GleifSource()
        self.team_id = 123
        self.config = GleifSourceConfig()

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True
