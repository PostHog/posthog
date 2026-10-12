from typing import cast

from sources.missive._config import MissiveSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MissiveSource(SimpleSource[MissiveSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MISSIVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MISSIVE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Missive",
            iconPath="/static/services/missive.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
