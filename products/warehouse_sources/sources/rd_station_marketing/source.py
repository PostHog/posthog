from typing import cast

from products.warehouse_sources.sources.rd_station_marketing._config import RDStationMarketingSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RDStationMarketingSource(SimpleSource[RDStationMarketingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RDSTATIONMARKETING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RDSTATIONMARKETING,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="RD Station Marketing",
            iconPath="/static/services/rd_station_marketing.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
