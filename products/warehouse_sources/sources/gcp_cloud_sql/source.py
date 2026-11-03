from typing import cast

from products.warehouse_sources.sources.gcp_cloud_sql._config import GcpCloudSqlSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpCloudSqlSource(SimpleSource[GcpCloudSqlSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDSQL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCLOUDSQL,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Google Cloud (Cloud SQL Admin API)",
            iconPath="/static/services/gcp_cloud_sql.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
