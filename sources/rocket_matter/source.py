from typing import cast

from sources.rocket_matter._config import RocketMatterSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RocketMatterSource(SimpleSource[RocketMatterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ROCKETMATTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ROCKETMATTER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Rocket Matter (ProfitSolv)",
            iconPath="/static/services/rocket_matter.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
