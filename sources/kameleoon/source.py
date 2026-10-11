from typing import cast

from sources.kameleoon._config import KameleoonSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KameleoonSource(SimpleSource[KameleoonSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAMELEOON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KAMELEOON,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Kameleoon",
            iconPath="/static/services/kameleoon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
