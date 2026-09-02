from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlemerchantcenter import (
    GoogleMerchantCenterSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleMerchantCenterSource(SimpleSource[GoogleMerchantCenterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEMERCHANTCENTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_MERCHANT_CENTER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Google Merchant Center",
            iconPath="/static/services/google_merchant_center.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
