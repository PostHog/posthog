from typing import cast

from sources.flexera_cloud_cost._config import FlexeraCloudCostSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FlexeraCloudCostSource(SimpleSource[FlexeraCloudCostSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLEXERACLOUDCOST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FLEXERACLOUDCOST,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Flexera",
            iconPath="/static/services/flexera_cloud_cost.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
