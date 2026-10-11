from typing import cast

from sources.five9._config import Five9SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class Five9Source(SimpleSource[Five9SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIVE9

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FIVE9,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Five9",
            iconPath="/static/services/five9.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
