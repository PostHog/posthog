from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SearchAds360SourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SearchAds360Source(SimpleSource[SearchAds360SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEARCHADS360

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SEARCH_ADS360,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["sa360"],
            label="Search Ads 360",
            iconPath="/static/services/search_ads_360.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
