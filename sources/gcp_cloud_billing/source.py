from typing import cast

from sources.gcp_cloud_billing._config import GcpCloudBillingSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudBillingSource(SimpleSource[GcpCloudBillingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDBILLING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDBILLING,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Google Cloud Platform (Cloud Billing)",
            iconPath="/static/services/gcp_cloud_billing.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
