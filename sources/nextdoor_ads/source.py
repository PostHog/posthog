from typing import cast

from sources.nextdoor_ads._config import NextdoorAdsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NextdoorAdsSource(SimpleSource[NextdoorAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEXTDOORADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NEXTDOORADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["nextdoor"],
            label="Nextdoor Ads",
            iconPath="/static/services/nextdoor.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
