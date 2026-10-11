from typing import cast

from sources.ledyer._config import LedyerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LedyerSource(SimpleSource[LedyerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEDYER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LEDYER,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Ledyer",
            iconPath="/static/services/ledyer.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
