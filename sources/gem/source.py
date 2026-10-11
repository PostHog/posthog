from typing import cast

from sources.gem._config import GemSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GemSource(SimpleSource[GemSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GEM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GEM,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Gem",
            iconPath="/static/services/gem.png",
            keywords=["ats", "recruiting", "hiring", "talent", "sourcing"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
