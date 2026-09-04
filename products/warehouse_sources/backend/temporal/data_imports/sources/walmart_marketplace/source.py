from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.walmartmarketplace import (
    WalmartMarketplaceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
