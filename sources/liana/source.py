from typing import cast

from sources.liana._config import LianaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LianaSource(SimpleSource[LianaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LIANA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LIANA,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Liana",
            iconPath="/static/services/liana.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
