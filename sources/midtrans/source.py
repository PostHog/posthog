from typing import cast

from sources.midtrans._config import MidtransSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MidtransSource(SimpleSource[MidtransSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MIDTRANS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MIDTRANS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Midtrans (GoTo Financial / PT Midtrans)",
            iconPath="/static/services/midtrans.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
