from typing import cast

from sources.criteo._config import CriteoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CriteoSource(SimpleSource[CriteoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRITEO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CRITEO,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Criteo",
            iconPath="/static/services/criteo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
