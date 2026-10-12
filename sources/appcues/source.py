from typing import cast

from sources.appcues._config import AppcuesSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AppcuesSource(SimpleSource[AppcuesSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPCUES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPCUES,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Appcues",
            iconPath="/static/services/appcues.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
