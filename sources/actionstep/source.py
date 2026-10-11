from typing import cast

from sources.actionstep._config import ActionstepSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ActionstepSource(SimpleSource[ActionstepSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ACTIONSTEP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ACTIONSTEP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Actionstep",
            iconPath="/static/services/actionstep.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
