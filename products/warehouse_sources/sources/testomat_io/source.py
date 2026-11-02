from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.testomatio import (
    TestomatioSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TestomatioSource(SimpleSource[TestomatioSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TESTOMATIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TESTOMATIO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Testomat.io",
            iconPath="/static/services/testomat_io.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
