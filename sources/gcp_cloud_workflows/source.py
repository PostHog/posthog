from typing import cast

from sources.gcp_cloud_workflows._config import GcpCloudWorkflowsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudWorkflowsSource(SimpleSource[GcpCloudWorkflowsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDWORKFLOWS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDWORKFLOWS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform",
            iconPath="/static/services/gcp_cloud_workflows.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
