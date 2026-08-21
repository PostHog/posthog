from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.writesonic import (
    WritesonicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.settings import WRITESONIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.source import WritesonicSource


class TestWritesonicSource:
    def setup_method(self):
        self.source = WritesonicSource()
        self.team_id = 123
        self.config = WritesonicSourceConfig(api_key="key_test", site_url="https://example.com")

    def test_primary_keys_are_exposed(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name, endpoint_config in WRITESONIC_ENDPOINTS.items():
            assert schemas[name].detected_primary_keys == endpoint_config.primary_keys
