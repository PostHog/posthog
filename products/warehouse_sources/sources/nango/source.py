from typing import cast

from products.warehouse_sources.sources.nango._config import NangoSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NangoSource(SimpleSource[NangoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NANGO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NANGO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Nango",
            iconPath="/static/services/nango.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
