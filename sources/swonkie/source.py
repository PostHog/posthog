from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.swonkie._config import SwonkieSourceConfig


@SourceRegistry.register
class SwonkieSource(SimpleSource[SwonkieSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SWONKIE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SWONKIE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Swonkie",
            iconPath="/static/services/swonkie.png",
            keywords=["social media", "social media management"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
