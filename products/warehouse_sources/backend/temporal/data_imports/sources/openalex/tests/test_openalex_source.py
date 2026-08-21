from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openalex import (
    OpenalexSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openalex.source import OpenalexSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.openalex.source"


class TestOpenalexSource:
    def setup_method(self) -> None:
        self.source = OpenalexSource()
        self.config = OpenalexSourceConfig(api_key="key")

    def test_incremental_fields_only_cover_known_endpoints(self) -> None:
        assert set(INCREMENTAL_FIELDS) <= set(ENDPOINTS)
