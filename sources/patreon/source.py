from typing import cast

from sources.patreon._config import PatreonSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PatreonSource(SimpleSource[PatreonSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PATREON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PATREON,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Patreon",
            iconPath="/static/services/patreon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
