from typing import cast

from sources.insightful._config import InsightfulSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class InsightfulSource(SimpleSource[InsightfulSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INSIGHTFUL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.INSIGHTFUL,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Insightful",
            iconPath="/static/services/insightful.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
