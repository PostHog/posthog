from typing import cast

from sources.pike13._config import Pike13SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class Pike13Source(SimpleSource[Pike13SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PIKE13

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PIKE13,
            category=DataWarehouseSourceCategory.CRM,
            label="Pike13",
            iconPath="/static/services/pike13.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
