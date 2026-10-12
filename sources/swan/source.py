from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.swan._config import SwanSourceConfig


@SourceRegistry.register
class SwanSource(SimpleSource[SwanSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SWAN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SWAN,
            category=DataWarehouseSourceCategory.CRM,
            label="Swan",
            iconPath="/static/services/swan.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
