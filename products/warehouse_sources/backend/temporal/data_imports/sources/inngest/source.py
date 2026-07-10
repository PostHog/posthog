from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InngestSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InngestSource(SimpleSource[InngestSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INNGEST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INNGEST,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Inngest",
            iconPath="/static/services/inngest.png",
            keywords=["workflow", "queue", "durable execution", "events"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
