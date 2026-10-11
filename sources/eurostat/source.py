from typing import cast

from sources.eurostat._config import EurostatSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class EurostatSource(SimpleSource[EurostatSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EUROSTAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EUROSTAT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Eurostat (European Commission)",
            iconPath="/static/services/eurostat.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
