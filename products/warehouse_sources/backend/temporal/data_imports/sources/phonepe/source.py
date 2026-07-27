from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.phonepe import (
    PhonepeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PhonepeSource(SimpleSource[PhonepeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PHONEPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PHONEPE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="PhonePe (PhonePe Payment Gateway / PhonePe Business)",
            iconPath="/static/services/phonepe.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
