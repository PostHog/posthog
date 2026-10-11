from typing import cast

from sources.samcart._config import SamCartSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SamCartSource(SimpleSource[SamCartSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAMCART

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAMCART,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="SamCart",
            iconPath="/static/services/samcart.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
