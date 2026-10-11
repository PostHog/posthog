from typing import cast

from sources.hootsuite._config import HootsuiteSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HootsuiteSource(SimpleSource[HootsuiteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOOTSUITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HOOTSUITE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Hootsuite",
            iconPath="/static/services/hootsuite.png",
            keywords=["social media", "social media management", "scheduling"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
