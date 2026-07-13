from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UpstashSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UpstashSource(SimpleSource[UpstashSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UPSTASH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UPSTASH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Upstash",
            iconPath="/static/services/upstash.png",
            keywords=["redis", "serverless", "qstash", "usage"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
