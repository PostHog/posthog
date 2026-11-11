from typing import cast

from products.warehouse_sources.sources.retreaver._config import RetreaverSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RetreaverSource(SimpleSource[RetreaverSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RETREAVER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RETREAVER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Retreaver",
            iconPath="/static/services/retreaver.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
