from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whop import WhopSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WhopSource(SimpleSource[WhopSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WHOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WHOP,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Whop",
            iconPath="/static/services/whop.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
