from typing import cast

from sources.gcp_cloud_functions._config import GcpCloudFunctionsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudFunctionsSource(SimpleSource[GcpCloudFunctionsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDFUNCTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDFUNCTIONS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Cloud Functions)",
            iconPath="/static/services/gcp_cloud_functions.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
