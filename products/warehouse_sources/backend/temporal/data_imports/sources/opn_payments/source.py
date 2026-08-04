from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opnpayments import (
    OpnPaymentsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpnPaymentsSource(SimpleSource[OpnPaymentsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPNPAYMENTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPN_PAYMENTS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Opn Payments (formerly Omise)",
            iconPath="/static/services/opn_payments.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
