from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoft365usagereports import (
    Microsoft365UsageReportsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Microsoft365UsageReportsSource(SimpleSource[Microsoft365UsageReportsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFT365USAGEREPORTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT365_USAGE_REPORTS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Microsoft (Microsoft Graph / Microsoft 365)",
            iconPath="/static/services/microsoft_365_usage_reports.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
