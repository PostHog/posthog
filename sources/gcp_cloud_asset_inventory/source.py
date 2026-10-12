from typing import cast

from sources.gcp_cloud_asset_inventory._config import GcpCloudAssetInventorySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudAssetInventorySource(SimpleSource[GcpCloudAssetInventorySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDASSETINVENTORY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDASSETINVENTORY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform (Cloud Asset Inventory)",
            iconPath="/static/services/gcp_cloud_asset_inventory.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
