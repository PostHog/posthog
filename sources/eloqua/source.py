from typing import cast

from sources.eloqua._config import EloquaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class EloquaSource(SimpleSource[EloquaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ELOQUA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ELOQUA,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["oracle eloqua"],
            label="Oracle Eloqua",
            iconPath="/static/services/eloqua.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
