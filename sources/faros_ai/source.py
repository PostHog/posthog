from typing import cast

from sources.faros_ai._config import FarosAiSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FarosAiSource(SimpleSource[FarosAiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FAROSAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FAROSAI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Faros AI",
            iconPath="/static/services/faros_ai.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
