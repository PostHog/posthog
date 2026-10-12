from typing import cast

from sources.bexio._config import BexioSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BexioSource(SimpleSource[BexioSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BEXIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BEXIO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Bexio",
            iconPath="/static/services/bexio.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
