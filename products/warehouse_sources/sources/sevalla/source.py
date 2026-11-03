from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.sevalla._config import SevallaSourceConfig


@SourceRegistry.register
class SevallaSource(SimpleSource[SevallaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEVALLA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEVALLA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sevalla",
            iconPath="/static/services/sevalla.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
