from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    RDStationMarketingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RDStationMarketingSource(SimpleSource[RDStationMarketingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RDSTATIONMARKETING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RD_STATION_MARKETING,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="RD Station Marketing",
            iconPath="/static/services/rd_station_marketing.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
