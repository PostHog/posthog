from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.simpro._config import SimproSourceConfig


@SourceRegistry.register
class SimproSource(SimpleSource[SimproSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIMPRO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SIMPRO,
            category=DataWarehouseSourceCategory.CRM,
            label="Simpro",
            iconPath="/static/services/simpro.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
