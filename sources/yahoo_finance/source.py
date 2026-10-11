from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.yahoo_finance._config import YahooFinanceSourceConfig


@SourceRegistry.register
class YahooFinanceSource(SimpleSource[YahooFinanceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YAHOOFINANCE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YAHOOFINANCE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Yahoo Finance",
            iconPath="/static/services/yahoo_finance.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
