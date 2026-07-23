from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpapigee import (
    GcpApigeeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpApigeeSource(SimpleSource[GcpApigeeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPAPIGEE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_APIGEE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Apigee API Management)",
            iconPath="/static/services/gcp_apigee.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
