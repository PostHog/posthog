from typing import cast

from sources.gcp_cloud_monitoring._config import GcpCloudMonitoringSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudMonitoringSource(SimpleSource[GcpCloudMonitoringSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDMONITORING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDMONITORING,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Monitoring (formerly Stackdriver)",
            iconPath="/static/services/gcp_cloud_monitoring.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
