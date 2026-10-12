from typing import cast

from sources.otto_market._config import OttoMarketSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OttoMarketSource(SimpleSource[OttoMarketSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OTTOMARKET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OTTOMARKET,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="OTTO Market (OTTO GmbH & Co KG)",
            iconPath="/static/services/otto_market.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
