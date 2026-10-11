from typing import cast

from sources.lokalise._config import LokaliseSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LokaliseSource(SimpleSource[LokaliseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOKALISE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOKALISE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Lokalise",
            iconPath="/static/services/lokalise.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
