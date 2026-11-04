from typing import cast

from products.warehouse_sources.sources.gcp_error_reporting._config import GcpErrorReportingSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpErrorReportingSource(SimpleSource[GcpErrorReportingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPERRORREPORTING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPERRORREPORTING,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Error Reporting)",
            iconPath="/static/services/gcp_error_reporting.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
