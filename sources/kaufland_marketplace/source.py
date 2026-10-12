from typing import cast

from sources.kaufland_marketplace._config import KauflandMarketplaceSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KauflandMarketplaceSource(SimpleSource[KauflandMarketplaceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAUFLANDMARKETPLACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KAUFLANDMARKETPLACE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Kaufland Global Marketplace (Kaufland Marketplace Seller API)",
            iconPath="/static/services/kaufland_marketplace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
