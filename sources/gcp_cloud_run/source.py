from typing import cast

from sources.gcp_cloud_run._config import GcpCloudRunSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudRunSource(SimpleSource[GcpCloudRunSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDRUN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDRUN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform (Cloud Run)",
            iconPath="/static/services/gcp_cloud_run.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
