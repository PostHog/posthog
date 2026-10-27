from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.woopayments import (
    WooPaymentsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
