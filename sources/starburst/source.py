from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.starburst._config import StarburstSourceConfig


@SourceRegistry.register
class StarburstSource(SimpleSource[StarburstSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STARBURST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STARBURST,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Starburst",
            iconPath="/static/services/starburst.png",
            keywords=["trino", "presto", "query engine"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
