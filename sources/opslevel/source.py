from typing import cast

from sources.opslevel._config import OpslevelSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OpslevelSource(SimpleSource[OpslevelSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPSLEVEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OPSLEVEL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="OpsLevel",
            iconPath="/static/services/opslevel.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
