from typing import cast

from products.warehouse_sources.sources.gcp_dataplex._config import GcpDataplexSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpDataplexSource(SimpleSource[GcpDataplexSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPDATAPLEX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPDATAPLEX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Dataplex)",
            iconPath="/static/services/gcp_dataplex.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
