from typing import cast

from products.warehouse_sources.sources.holded._config import HoldedSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HoldedSource(SimpleSource[HoldedSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOLDED

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HOLDED,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Holded (Visma)",
            iconPath="/static/services/holded.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
