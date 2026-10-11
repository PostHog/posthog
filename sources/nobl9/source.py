from typing import cast

from sources.nobl9._config import Nobl9SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class Nobl9Source(SimpleSource[Nobl9SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOBL9

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NOBL9,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Nobl9",
            iconPath="/static/services/nobl9.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
