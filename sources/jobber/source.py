from typing import cast

from sources.jobber._config import JobberSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class JobberSource(SimpleSource[JobberSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JOBBER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.JOBBER,
            category=DataWarehouseSourceCategory.CRM,
            label="Jobber",
            iconPath="/static/services/jobber.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
