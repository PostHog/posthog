from typing import cast

from sources.gcp_cloud_logging._config import GcpCloudLoggingSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudLoggingSource(SimpleSource[GcpCloudLoggingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDLOGGING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDLOGGING,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform",
            iconPath="/static/services/gcp_cloud_logging.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
