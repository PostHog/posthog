from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlewebfonts import (
    GoogleWebfontsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.source import GoogleWebfontsSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.source"


class TestGoogleWebfontsSource:
    def setup_method(self):
        self.source = GoogleWebfontsSource()
        self.team_id = 123
        self.config = GoogleWebfontsSourceConfig(api_key="AIza-key")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["webfonts"])
        assert len(schemas) == 1
        assert schemas[0].name == "webfonts"
