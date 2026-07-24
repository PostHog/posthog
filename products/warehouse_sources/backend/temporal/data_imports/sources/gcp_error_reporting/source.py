from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcperrorreporting import (
    GcpErrorReportingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpErrorReportingSource(SimpleSource[GcpErrorReportingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPERRORREPORTING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_ERROR_REPORTING,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Error Reporting)",
            iconPath="/static/services/gcp_error_reporting.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
