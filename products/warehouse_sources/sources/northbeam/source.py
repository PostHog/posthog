from typing import cast

from products.warehouse_sources.sources.northbeam._config import NorthbeamSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NorthbeamSource(SimpleSource[NorthbeamSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NORTHBEAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NORTHBEAM,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Northbeam",
            iconPath="/static/services/northbeam.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
