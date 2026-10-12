from typing import cast

from sources.collibra._config import CollibraSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CollibraSource(SimpleSource[CollibraSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COLLIBRA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COLLIBRA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Collibra",
            iconPath="/static/services/collibra.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
