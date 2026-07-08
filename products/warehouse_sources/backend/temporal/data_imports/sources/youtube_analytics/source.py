from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    YouTubeAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YouTubeAnalyticsSource(SimpleSource[YouTubeAnalyticsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOUTUBEANALYTICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.YOU_TUBE_ANALYTICS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="YouTube Analytics",
            iconPath="/static/services/youtube_analytics.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
