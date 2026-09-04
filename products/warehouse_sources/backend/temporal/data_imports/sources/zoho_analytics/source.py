from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zohoanalytics import (
    ZohoAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
