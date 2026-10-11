from typing import cast

from sources.perk._config import PerkSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PerkSource(SimpleSource[PerkSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PERK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PERK,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Perk",
            iconPath="/static/services/perk.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
