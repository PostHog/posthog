from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tradablebits import (
    TradableBitsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TradableBitsSource(SimpleSource[TradableBitsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRADABLEBITS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRADABLEBITS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Tradable Bits",
            iconPath="/static/services/tradablebits.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
