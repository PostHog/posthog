from typing import cast

from products.warehouse_sources.sources.gcp_apigee._config import GcpApigeeSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpApigeeSource(SimpleSource[GcpApigeeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPAPIGEE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPAPIGEE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Apigee API Management)",
            iconPath="/static/services/gcp_apigee.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
