from typing import cast

from sources.allegro._config import AllegroSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AllegroSource(SimpleSource[AllegroSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ALLEGRO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ALLEGRO,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Allegro (Allegro.pl sp. z o.o.)",
            iconPath="/static/services/allegro.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
