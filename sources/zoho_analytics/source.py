from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zoho_analytics._config import ZohoAnalyticsSourceConfig


@SourceRegistry.register
class ZohoAnalyticsSource(SimpleSource[ZohoAnalyticsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOANALYTICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHOANALYTICS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Zoho Analytics",
            iconPath="/static/services/zoho_analytics.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
