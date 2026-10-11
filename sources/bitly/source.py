from typing import cast

from sources.bitly._config import BitlySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BitlySource(SimpleSource[BitlySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BITLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BITLY,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Bitly",
            iconPath="/static/services/bitly.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
