from typing import cast

from sources.hostaway._config import HostawaySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HostawaySource(SimpleSource[HostawaySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOSTAWAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HOSTAWAY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Hostaway",
            iconPath="/static/services/hostaway.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
