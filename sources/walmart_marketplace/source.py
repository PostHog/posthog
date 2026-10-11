from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.walmart_marketplace._config import WalmartMarketplaceSourceConfig


@SourceRegistry.register
class WalmartMarketplaceSource(SimpleSource[WalmartMarketplaceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WALMARTMARKETPLACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WALMARTMARKETPLACE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Walmart Marketplace (Walmart Seller API)",
            iconPath="/static/services/walmart_marketplace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
