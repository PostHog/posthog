from products.warehouse_sources.sources.boldsign._config import BoldSignSourceConfig
from products.warehouse_sources.sources.boldsign.source import BoldSignSource


class TestBoldSignSource:
    def setup_method(self):
        self.source = BoldSignSource()
        self.team_id = 123
        self.config = BoldSignSourceConfig(api_key="key", region="us")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog (no I/O) so the public docs can render Supported tables.
        assert self.source.lists_tables_without_credentials is True
