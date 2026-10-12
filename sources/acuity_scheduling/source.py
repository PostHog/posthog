from typing import cast

from sources.acuity_scheduling._config import AcuitySchedulingSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AcuitySchedulingSource(SimpleSource[AcuitySchedulingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ACUITYSCHEDULING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ACUITYSCHEDULING,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Acuity Scheduling",
            iconPath="/static/services/acuity_scheduling.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
