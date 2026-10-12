from typing import cast

from sources.gcp_cloud_trace._config import GcpCloudTraceSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudTraceSource(SimpleSource[GcpCloudTraceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDTRACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDTRACE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Cloud Trace)",
            iconPath="/static/services/gcp_cloud_trace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
