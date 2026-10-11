from typing import cast

from sources.rewardful._config import RewardfulSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RewardfulSource(SimpleSource[RewardfulSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REWARDFUL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REWARDFUL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Rewardful",
            iconPath="/static/services/rewardful.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
