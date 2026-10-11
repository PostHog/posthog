from typing import cast

from sources.dokploy._config import DokploySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DokploySource(SimpleSource[DokploySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOKPLOY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DOKPLOY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Dokploy",
            keywords=["dokploy.com"],
            iconPath="/static/services/dokploy.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
