from typing import cast

from sources.klarna._config import KlarnaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KlarnaSource(SimpleSource[KlarnaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KLARNA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KLARNA,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Klarna",
            iconPath="/static/services/klarna.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
