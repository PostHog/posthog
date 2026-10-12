from typing import cast

from sources.drchrono._config import DrchronoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DrchronoSource(SimpleSource[DrchronoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DRCHRONO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DRCHRONO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="DrChrono (EverHealth)",
            iconPath="/static/services/drchrono.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
