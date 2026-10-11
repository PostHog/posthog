from typing import cast

from sources.alpaca_broker_api._config import AlpacaBrokerAPISourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AlpacaBrokerAPISource(SimpleSource[AlpacaBrokerAPISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ALPACABROKERAPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ALPACABROKERAPI,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Alpaca Broker API",
            iconPath="/static/services/alpaca_broker_api.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
