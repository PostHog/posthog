from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flexeracloudcost import (
    FlexeraCloudCostSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FlexeraCloudCostSource(SimpleSource[FlexeraCloudCostSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLEXERACLOUDCOST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLEXERA_CLOUD_COST,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Flexera",
            iconPath="/static/services/flexera_cloud_cost.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
