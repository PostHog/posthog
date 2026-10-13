from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ip2whois import (
    IP2WhoisSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.source import IP2WhoisSource


class TestIP2WhoisSource:
    def setup_method(self):
        self.source = IP2WhoisSource()
        self.team_id = 123
        self.config = IP2WhoisSourceConfig(api_key="test-key", domains="example.com")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — must opt in so public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self):
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["whois"])] == ["whois"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []
