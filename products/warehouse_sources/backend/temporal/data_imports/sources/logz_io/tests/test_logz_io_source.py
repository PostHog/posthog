from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logzio import LogzIOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.source import LogzIOSource

SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.source"


class TestLogzIOSource:
    def setup_method(self):
        self.source = LogzIOSource()
        self.team_id = 123
        self.config = LogzIOSourceConfig(api_token="token", region="us")

    def test_connection_host_fields_includes_region(self):
        # region picks the host the stored token is sent to, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["region"]
