from typing import cast

from sources.blackboard_learn._config import BlackboardLearnSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BlackboardLearnSource(SimpleSource[BlackboardLearnSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLACKBOARDLEARN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BLACKBOARDLEARN,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Anthology Blackboard Learn",
            iconPath="/static/services/blackboard_learn.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
