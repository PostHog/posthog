from typing import cast

from sources.pingone._config import PingoneSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PingoneSource(SimpleSource[PingoneSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PINGONE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PINGONE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Ping Identity (PingOne)",
            iconPath="/static/services/pingone.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
