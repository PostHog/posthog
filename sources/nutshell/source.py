from typing import cast

from sources.nutshell._config import NutshellSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NutshellSource(SimpleSource[NutshellSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NUTSHELL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NUTSHELL,
            category=DataWarehouseSourceCategory.CRM,
            label="Nutshell",
            iconPath="/static/services/nutshell.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
