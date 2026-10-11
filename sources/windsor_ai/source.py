from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.windsor_ai._config import WindsorAiSourceConfig


@SourceRegistry.register
class WindsorAiSource(SimpleSource[WindsorAiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WINDSORAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WINDSORAI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Windsor.ai",
            iconPath="/static/services/windsor_ai.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
