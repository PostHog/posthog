from typing import cast

from products.warehouse_sources.sources.gcp_gke._config import GcpGkeSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpGkeSource(SimpleSource[GcpGkeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPGKE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPGKE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Google Kubernetes Engine)",
            iconPath="/static/services/gcp_gke.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
