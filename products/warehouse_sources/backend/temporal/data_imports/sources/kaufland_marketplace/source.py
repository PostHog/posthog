from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kauflandmarketplace import (
    KauflandMarketplaceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KauflandMarketplaceSource(SimpleSource[KauflandMarketplaceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAUFLANDMARKETPLACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KAUFLAND_MARKETPLACE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Kaufland Global Marketplace (Kaufland Marketplace Seller API)",
            iconPath="/static/services/kaufland_marketplace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
