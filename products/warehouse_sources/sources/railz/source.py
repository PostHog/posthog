from typing import cast

from products.warehouse_sources.sources.railz._config import RailzSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RailzSource(SimpleSource[RailzSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAILZ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RAILZ,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Railz",
            iconPath="/static/services/railz.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
