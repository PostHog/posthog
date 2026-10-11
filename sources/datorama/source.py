from typing import cast

from sources.datorama._config import DatoramaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DatoramaSource(SimpleSource[DatoramaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATORAMA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DATORAMA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["salesforce", "marketing cloud intelligence"],
            label="Datorama",
            iconPath="/static/services/datorama.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
