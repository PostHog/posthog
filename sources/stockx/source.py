from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.stockx._config import StockxSourceConfig


@SourceRegistry.register
class StockxSource(SimpleSource[StockxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STOCKX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STOCKX,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="StockX (StockX Public API)",
            iconPath="/static/services/stockx.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
