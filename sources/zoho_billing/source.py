from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zoho_billing._config import ZohoBillingSourceConfig


@SourceRegistry.register
class ZohoBillingSource(SimpleSource[ZohoBillingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOBILLING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHOBILLING,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Zoho Billing",
            iconPath="/static/services/zoho_billing.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
