from typing import cast

from sources.bling._config import BlingSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BlingSource(SimpleSource[BlingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BLING,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Bling (Bling ERP, by Trided/LWSA)",
            iconPath="/static/services/bling.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
