from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.five9._config import Five9SourceConfig


@SourceRegistry.register
class Five9Source(SimpleSource[Five9SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIVE9

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FIVE9,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Five9",
            iconPath="/static/services/five9.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
