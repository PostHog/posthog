from typing import cast

from products.warehouse_sources.sources.google_admob._config import GoogleAdMobSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleAdMobSource(SimpleSource[GoogleAdMobSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADMOB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEADMOB,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Google AdMob",
            iconPath="/static/services/google_admob.png",
            keywords=["admob", "ads"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
