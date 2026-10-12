from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.tradable_bits._config import TradableBitsSourceConfig


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
