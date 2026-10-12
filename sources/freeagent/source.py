from typing import cast

from sources.freeagent._config import FreeAgentSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FreeAgentSource(SimpleSource[FreeAgentSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FREEAGENT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FREEAGENT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="FreeAgent",
            iconPath="/static/services/freeagent.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
