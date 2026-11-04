from typing import cast

from products.warehouse_sources.sources.podium._config import PodiumSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PodiumSource(SimpleSource[PodiumSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PODIUM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PODIUM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Podium",
            iconPath="/static/services/podium.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
