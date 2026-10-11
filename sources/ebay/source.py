from typing import cast

from sources.ebay._config import EbaySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class EbaySource(SimpleSource[EbaySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EBAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EBAY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="eBay",
            iconPath="/static/services/ebay.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
