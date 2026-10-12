from typing import cast

from sources.apaleo._config import ApaleoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ApaleoSource(SimpleSource[ApaleoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APALEO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APALEO,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Apaleo",
            iconPath="/static/services/apaleo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
