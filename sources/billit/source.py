from typing import cast

from sources.billit._config import BillitSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BillitSource(SimpleSource[BillitSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BILLIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BILLIT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Billit",
            iconPath="/static/services/billit.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
