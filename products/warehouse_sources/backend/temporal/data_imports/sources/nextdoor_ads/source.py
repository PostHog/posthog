from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NextdoorAdsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NextdoorAdsSource(SimpleSource[NextdoorAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEXTDOORADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NEXTDOOR_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["nextdoor"],
            label="Nextdoor Ads",
            iconPath="/static/services/nextdoor.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
