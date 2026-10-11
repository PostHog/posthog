from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.thrive_learning._config import ThriveLearningSourceConfig


@SourceRegistry.register
class ThriveLearningSource(SimpleSource[ThriveLearningSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THRIVELEARNING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.THRIVELEARNING,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Thrive Learning",
            iconPath="/static/services/thrive_learning.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
