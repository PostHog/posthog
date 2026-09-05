from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.youtubedata import (
    YoutubeDataSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YoutubeDataSource(SimpleSource[YoutubeDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOUTUBEDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YOUTUBEDATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="YouTube Data",
            iconPath="/static/services/youtube_data.png",
            keywords=["youtube", "yt"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
