from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.woopayments._config import WooPaymentsSourceConfig


@SourceRegistry.register
class WooPaymentsSource(SimpleSource[WooPaymentsSourceConfig]):
    api_docs_url = "https://automattic.github.io/woocommerce-payments/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WOOPAYMENTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WOOPAYMENTS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            keywords=["woocommerce payments"],
            label="WooPayments",
            iconPath="/static/services/woopayments.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
