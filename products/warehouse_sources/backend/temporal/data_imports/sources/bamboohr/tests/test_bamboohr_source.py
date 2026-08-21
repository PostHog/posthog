from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.source import BambooHRSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.source"


class TestBambooHRSource:
    def test_source_type(self) -> None:
        assert BambooHRSource().source_type == ExternalDataSourceType.BAMBOOHR
