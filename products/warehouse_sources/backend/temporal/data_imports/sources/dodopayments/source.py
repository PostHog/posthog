from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DodoPaymentsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DodoPaymentsSource(SimpleSource[DodoPaymentsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DODOPAYMENTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DODO_PAYMENTS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Dodo Payments",
            iconPath="/static/services/dodopayments.png",
            keywords=["payments", "billing", "merchant of record"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
