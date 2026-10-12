from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.vturb._config import VturbSourceConfig


@SourceRegistry.register
class VturbSource(SimpleSource[VturbSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VTURB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VTURB,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Vturb",
            iconPath="/static/services/vturb.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
