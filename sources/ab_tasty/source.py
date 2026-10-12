from typing import cast

from sources.ab_tasty._config import AbTastySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AbTastySource(SimpleSource[AbTastySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ABTASTY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ABTASTY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="AB Tasty",
            iconPath="/static/services/ab_tasty.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
