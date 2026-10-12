from typing import cast

from products.warehouse_sources.sources.clevertap._config import ClevertapSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ClevertapSource(SimpleSource[ClevertapSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLEVERTAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLEVERTAP,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="CleverTap",
            iconPath="/static/services/clevertap.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
