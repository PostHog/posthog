from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudtrace import (
    GcpCloudTraceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpCloudTraceSource(SimpleSource[GcpCloudTraceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDTRACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_CLOUD_TRACE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Cloud Trace)",
            iconPath="/static/services/gcp_cloud_trace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
