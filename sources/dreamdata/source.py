from typing import cast

from sources.dreamdata._config import DreamdataSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DreamdataSource(SimpleSource[DreamdataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DREAMDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DREAMDATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Dreamdata",
            iconPath="/static/services/dreamdata.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
