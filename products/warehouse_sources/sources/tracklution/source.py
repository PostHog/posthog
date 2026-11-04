from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.tracklution._config import TracklutionSourceConfig


@SourceRegistry.register
class TracklutionSource(SimpleSource[TracklutionSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRACKLUTION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRACKLUTION,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Tracklution",
            iconPath="/static/services/tracklution.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
