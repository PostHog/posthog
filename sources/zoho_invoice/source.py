from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zoho_invoice._config import ZohoInvoiceSourceConfig


@SourceRegistry.register
class ZohoInvoiceSource(SimpleSource[ZohoInvoiceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOINVOICE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHOINVOICE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Zoho Invoice",
            iconPath="/static/services/zoho_invoice.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
