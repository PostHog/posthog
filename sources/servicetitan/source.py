from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.servicetitan._config import ServicetitanSourceConfig


@SourceRegistry.register
class ServicetitanSource(SimpleSource[ServicetitanSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SERVICETITAN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SERVICETITAN,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="ServiceTitan",
            iconPath="/static/services/servicetitan.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
