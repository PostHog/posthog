from typing import cast

from sources.atlan._config import AtlanSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AtlanSource(SimpleSource[AtlanSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ATLAN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ATLAN,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Atlan",
            iconPath="/static/services/atlan.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
