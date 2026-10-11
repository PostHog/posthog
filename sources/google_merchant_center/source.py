from typing import cast

from sources.google_merchant_center._config import GoogleMerchantCenterSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleMerchantCenterSource(SimpleSource[GoogleMerchantCenterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEMERCHANTCENTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEMERCHANTCENTER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Google Merchant Center",
            iconPath="/static/services/google_merchant_center.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
