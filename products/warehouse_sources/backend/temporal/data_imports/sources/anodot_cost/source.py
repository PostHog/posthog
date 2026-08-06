from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.anodotcost import (
    AnodotCostSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AnodotCostSource(SimpleSource[AnodotCostSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ANODOTCOST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ANODOT_COST,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Anodot Cost (Umbrella Cost)",
            iconPath="/static/services/anodot_cost.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
