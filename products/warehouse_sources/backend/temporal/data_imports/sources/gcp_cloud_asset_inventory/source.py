from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudassetinventory import (
    GcpCloudAssetInventorySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpCloudAssetInventorySource(SimpleSource[GcpCloudAssetInventorySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDASSETINVENTORY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_CLOUD_ASSET_INVENTORY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform (Cloud Asset Inventory)",
            iconPath="/static/services/gcp_cloud_asset_inventory.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
