from typing import cast

from sources.rakuten_advertising._config import RakutenAdvertisingSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RakutenAdvertisingSource(SimpleSource[RakutenAdvertisingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAKUTENADVERTISING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RAKUTENADVERTISING,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Rakuten Advertising",
            iconPath="/static/services/rakuten_advertising.png",
            keywords=["linkshare", "affiliate", "rakuten marketing"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
