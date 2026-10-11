from typing import cast

from sources.box._config import BoxSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BoxSource(SimpleSource[BoxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BOX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BOX,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Box",
            iconPath="/static/services/box.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
