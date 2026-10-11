from typing import cast

from sources.ikas._config import IkasSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class IkasSource(SimpleSource[IkasSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IKAS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.IKAS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="ikas",
            iconPath="/static/services/ikas.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
