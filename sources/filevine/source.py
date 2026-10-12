from typing import cast

from sources.filevine._config import FilevineSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FilevineSource(SimpleSource[FilevineSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FILEVINE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FILEVINE,
            category=DataWarehouseSourceCategory.SALES,
            label="Filevine",
            iconPath="/static/services/filevine.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
