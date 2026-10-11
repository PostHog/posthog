from typing import cast

from sources.microsoft_365_usage_reports._config import Microsoft365UsageReportsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class Microsoft365UsageReportsSource(SimpleSource[Microsoft365UsageReportsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFT365USAGEREPORTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFT365USAGEREPORTS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Microsoft (Microsoft Graph / Microsoft 365)",
            iconPath="/static/services/microsoft_365_usage_reports.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
