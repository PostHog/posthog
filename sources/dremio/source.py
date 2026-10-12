from typing import cast

from sources.dremio._config import DremioSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DremioSource(SimpleSource[DremioSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DREMIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DREMIO,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql"],
            label="Dremio",
            iconPath="/static/services/dremio.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
