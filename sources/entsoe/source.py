from typing import cast

from sources.entsoe._config import EntsoeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class EntsoeSource(SimpleSource[EntsoeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ENTSOE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ENTSOE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="ENTSO-E Transparency Platform",
            iconPath="/static/services/entsoe.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
