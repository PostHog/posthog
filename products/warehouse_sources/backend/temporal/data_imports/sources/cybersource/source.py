from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cybersource import (
    CybersourceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CybersourceSource(SimpleSource[CybersourceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CYBERSOURCE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CYBERSOURCE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Cybersource",
            iconPath="/static/services/cybersource.png",
            keywords=["payments", "visa"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
