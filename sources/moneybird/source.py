from typing import cast

from sources.moneybird._config import MoneybirdSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MoneybirdSource(SimpleSource[MoneybirdSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONEYBIRD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MONEYBIRD,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Moneybird",
            iconPath="/static/services/moneybird.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
