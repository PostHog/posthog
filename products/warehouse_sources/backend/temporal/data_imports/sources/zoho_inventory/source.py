from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZohoInventorySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZohoInventorySource(SimpleSource[ZohoInventorySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOINVENTORY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZOHO_INVENTORY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Zoho Inventory",
            iconPath="/static/services/zoho_inventory.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
