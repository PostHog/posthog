from typing import cast

from products.warehouse_sources.sources.convonite._config import ConvoniteSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ConvoniteSource(SimpleSource[ConvoniteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONVONITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CONVONITE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Convonite",
            iconPath="/static/services/convonite.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
