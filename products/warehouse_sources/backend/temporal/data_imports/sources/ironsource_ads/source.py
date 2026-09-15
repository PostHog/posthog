from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ironsourceads import (
    IronSourceAdsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
