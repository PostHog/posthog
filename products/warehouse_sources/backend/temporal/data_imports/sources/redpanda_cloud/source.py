from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.redpandacloud import (
    RedpandaCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RedpandaCloudSource(SimpleSource[RedpandaCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REDPANDACLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REDPANDACLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Redpanda Data (Redpanda Cloud)",
            iconPath="/static/services/redpanda_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
