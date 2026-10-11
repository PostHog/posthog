from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.vwo._config import VWOSourceConfig


@SourceRegistry.register
class VWOSource(SimpleSource[VWOSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VWO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VWO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="VWO",
            iconPath="/static/services/vwo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
