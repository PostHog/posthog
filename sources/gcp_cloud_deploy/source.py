from typing import cast

from sources.gcp_cloud_deploy._config import GcpCloudDeploySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudDeploySource(SimpleSource[GcpCloudDeploySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDDEPLOY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDDEPLOY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Google Cloud Deploy)",
            iconPath="/static/services/gcp_cloud_deploy.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
