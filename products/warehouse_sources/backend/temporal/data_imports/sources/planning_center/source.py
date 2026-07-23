from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.planningcenter import (
    PlanningCenterSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlanningCenterSource(SimpleSource[PlanningCenterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLANNINGCENTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLANNING_CENTER,
            category=DataWarehouseSourceCategory.CRM,
            label="Planning Center (Ministry Centered Technologies)",
            iconPath="/static/services/planning_center.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
