from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ReplicateSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ReplicateSource(SimpleSource[ReplicateSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REPLICATE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REPLICATE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Replicate",
            iconPath="/static/services/replicate.png",
            keywords=["ml", "ai", "models", "inference"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
