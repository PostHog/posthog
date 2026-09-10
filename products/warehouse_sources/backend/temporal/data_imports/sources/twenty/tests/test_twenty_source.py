from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twenty import TwentySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.source import TwentySource


class TestTwentySource:
    def setup_method(self):
        self.source = TwentySource()
        self.team_id = 123
        self.config = TwentySourceConfig(api_key="tok", base_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The API key is sent to base_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["base_url"]

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
