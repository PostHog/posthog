from typing import cast

from sources.gcp_cloud_spanner._config import GcpCloudSpannerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudSpannerSource(SimpleSource[GcpCloudSpannerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDSPANNER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDSPANNER,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Google Cloud (Google LLC)",
            iconPath="/static/services/gcp_cloud_spanner.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
