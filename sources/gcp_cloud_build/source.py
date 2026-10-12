from typing import cast

from sources.gcp_cloud_build._config import GcpCloudBuildSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudBuildSource(SimpleSource[GcpCloudBuildSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDBUILD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDBUILD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform (Cloud Build)",
            iconPath="/static/services/gcp_cloud_build.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
