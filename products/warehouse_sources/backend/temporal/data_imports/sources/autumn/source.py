from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AutumnSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AutumnSource(SimpleSource[AutumnSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AUTUMN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AUTUMN,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Autumn",
            iconPath="/static/services/autumn.png",
            keywords=["billing", "subscriptions", "useautumn"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
