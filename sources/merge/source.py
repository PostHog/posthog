from typing import cast

from sources.merge._config import MergeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MergeSource(SimpleSource[MergeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MERGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MERGE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Merge",
            iconPath="/static/services/merge.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
