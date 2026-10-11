from typing import cast

from sources.chargebackstop._config import ChargebackStopSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ChargebackStopSource(SimpleSource[ChargebackStopSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHARGEBACKSTOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHARGEBACKSTOP,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="ChargebackStop",
            iconPath="/static/services/chargebackstop.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
