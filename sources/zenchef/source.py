from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zenchef._config import ZenchefSourceConfig


@SourceRegistry.register
class ZenchefSource(SimpleSource[ZenchefSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENCHEF

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZENCHEF,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Zenchef",
            iconPath="/static/services/zenchef.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
