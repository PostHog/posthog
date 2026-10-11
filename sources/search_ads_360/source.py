from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.search_ads_360._config import SearchAds360SourceConfig


@SourceRegistry.register
class SearchAds360Source(SimpleSource[SearchAds360SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEARCHADS360

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEARCHADS360,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["sa360"],
            label="Search Ads 360",
            iconPath="/static/services/search_ads_360.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
