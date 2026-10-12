from typing import cast

from sources.planning_center._config import PlanningCenterSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PlanningCenterSource(SimpleSource[PlanningCenterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLANNINGCENTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PLANNINGCENTER,
            category=DataWarehouseSourceCategory.CRM,
            label="Planning Center (Ministry Centered Technologies)",
            iconPath="/static/services/planning_center.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
