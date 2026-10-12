from typing import cast

from products.warehouse_sources.sources.flexport._config import FlexportSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FlexportSource(SimpleSource[FlexportSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLEXPORT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FLEXPORT,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Flexport",
            iconPath="/static/services/flexport.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
