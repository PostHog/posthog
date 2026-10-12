from typing import cast

from sources.inth._config import InthSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class InthSource(SimpleSource[InthSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INTH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.INTH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Inth",
            iconPath="/static/services/inth.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
