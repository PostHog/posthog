from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.gcp_apigee._config import GcpApigeeSourceConfig


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
