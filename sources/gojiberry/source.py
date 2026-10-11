from typing import cast

from sources.gojiberry._config import GojiberrySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GojiberrySource(SimpleSource[GojiberrySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOJIBERRY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOJIBERRY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Gojiberry",
            iconPath="/static/services/gojiberry.png",
            keywords=["survey", "surveys"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
