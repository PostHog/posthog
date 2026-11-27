from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.testomat_io._config import TestomatioSourceConfig


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
