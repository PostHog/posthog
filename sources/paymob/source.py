from typing import cast

from sources.paymob._config import PaymobSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PaymobSource(SimpleSource[PaymobSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAYMOB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PAYMOB,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Paymob",
            iconPath="/static/services/paymob.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
