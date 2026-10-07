from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.testdino import (
    TestDinoSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TestDinoSource(SimpleSource[TestDinoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TESTDINO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TESTDINO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="TestDino",
            keywords=["playwright"],
            iconPath="/static/services/testdino.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
