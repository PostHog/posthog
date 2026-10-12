from typing import cast

from products.warehouse_sources.sources.microsoft_advertising._config import MicrosoftAdvertisingSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftAdvertisingSource(SimpleSource[MicrosoftAdvertisingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTADVERTISING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTADVERTISING,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Microsoft Advertising (Bing Ads)",
            iconPath="/static/services/microsoft_advertising.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
