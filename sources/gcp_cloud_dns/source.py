from typing import cast

from sources.gcp_cloud_dns._config import GcpCloudDnsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudDnsSource(SimpleSource[GcpCloudDnsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDDNS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDDNS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform (Cloud DNS)",
            iconPath="/static/services/gcp_cloud_dns.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
