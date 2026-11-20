from typing import cast

from products.warehouse_sources.sources.phonepe._config import PhonepeSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PhonepeSource(SimpleSource[PhonepeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PHONEPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PHONEPE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="PhonePe (PhonePe Payment Gateway / PhonePe Business)",
            iconPath="/static/services/phonepe.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
