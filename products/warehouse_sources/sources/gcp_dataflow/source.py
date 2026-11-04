from typing import cast

from products.warehouse_sources.sources.gcp_dataflow._config import GcpDataflowSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpDataflowSource(SimpleSource[GcpDataflowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPDATAFLOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPDATAFLOW,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Dataflow",
            iconPath="/static/services/gcp_dataflow.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
