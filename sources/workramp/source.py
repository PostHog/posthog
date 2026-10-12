from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.workramp._config import WorkrampSourceConfig


@SourceRegistry.register
class WorkrampSource(SimpleSource[WorkrampSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKRAMP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WORKRAMP,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Workramp",
            iconPath="/static/services/workramp.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
