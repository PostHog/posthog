from typing import cast

from sources.directus._config import DirectusSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DirectusSource(SimpleSource[DirectusSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DIRECTUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DIRECTUS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Directus",
            iconPath="/static/services/directus.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
