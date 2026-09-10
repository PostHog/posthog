from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.commissionjunction import (
    CommissionJunctionSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CommissionJunctionSource(SimpleSource[CommissionJunctionSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COMMISSIONJUNCTION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COMMISSION_JUNCTION,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Commission Junction",
            iconPath="/static/services/commission_junction.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
