from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ClickhouseCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClickhouseCloudSource(SimpleSource[ClickhouseCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLICKHOUSECLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLICKHOUSE_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="ClickHouse Cloud (ClickHouse, Inc.)",
            iconPath="/static/services/clickhouse_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
