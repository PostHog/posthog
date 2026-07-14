from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RudderStackSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RudderStackSource(SimpleSource[RudderStackSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RUDDERSTACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RUDDER_STACK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="RudderStack",
            iconPath="/static/services/rudderstack.png",
            keywords=["cdp", "customer data platform", "event streaming"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
