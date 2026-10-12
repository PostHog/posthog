from typing import cast

from sources.mendeley._config import MendeleySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MendeleySource(SimpleSource[MendeleySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MENDELEY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MENDELEY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Mendeley",
            iconPath="/static/services/mendeley.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
