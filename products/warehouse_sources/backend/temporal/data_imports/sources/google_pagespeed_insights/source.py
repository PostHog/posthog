from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GooglePageSpeedInsightsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GooglePageSpeedInsightsSource(SimpleSource[GooglePageSpeedInsightsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEPAGESPEEDINSIGHTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_PAGE_SPEED_INSIGHTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google PageSpeed Insights",
            iconPath="/static/services/google_pagespeed_insights.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
