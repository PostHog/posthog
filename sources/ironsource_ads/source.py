from typing import cast

from sources.ironsource_ads._config import IronSourceAdsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class IronSourceAdsSource(SimpleSource[IronSourceAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IRONSOURCEADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.IRONSOURCEADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["ironsource", "mobile ads", "monetization"],
            label="ironSource Ads",
            iconPath="/static/services/ironsource_ads.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
