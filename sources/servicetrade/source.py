from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.servicetrade._config import ServicetradeSourceConfig


@SourceRegistry.register
class ServicetradeSource(SimpleSource[ServicetradeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SERVICETRADE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SERVICETRADE,
            category=DataWarehouseSourceCategory.SALES,
            label="ServiceTrade",
            iconPath="/static/services/servicetrade.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
