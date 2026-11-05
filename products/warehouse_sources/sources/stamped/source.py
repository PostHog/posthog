from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.stamped._config import StampedSourceConfig


@SourceRegistry.register
class StampedSource(SimpleSource[StampedSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STAMPED

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STAMPED,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Stamped",
            iconPath="/static/services/stamped.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
