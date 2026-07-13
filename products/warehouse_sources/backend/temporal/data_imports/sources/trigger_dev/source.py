from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TriggerDevSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TriggerDevSource(SimpleSource[TriggerDevSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRIGGERDEV

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRIGGER_DEV,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Trigger.dev",
            iconPath="/static/services/trigger_dev.png",
            keywords=["background jobs", "workflows", "task runs", "queues"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
