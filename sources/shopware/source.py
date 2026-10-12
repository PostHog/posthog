from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.shopware._config import ShopwareSourceConfig


@SourceRegistry.register
class ShopwareSource(SimpleSource[ShopwareSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHOPWARE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SHOPWARE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Shopware",
            iconPath="/static/services/shopware.png",
            keywords=["shopware 6", "ecommerce", "shop"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
