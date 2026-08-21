from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.granola import (
    GranolaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.source import GranolaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGranolaSource:
    def setup_method(self):
        self.source = GranolaSource()
        self.team_id = 123
        self.config = GranolaSourceConfig(api_key="grn_test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GRANOLA
