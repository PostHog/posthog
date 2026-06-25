from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    AmazonEventBridgeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmazonEventBridgeSource(SimpleSource[AmazonEventBridgeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONEVENTBRIDGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AMAZON_EVENT_BRIDGE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon EventBridge",
            iconPath="/static/services/amazon_eventbridge.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
