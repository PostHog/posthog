from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudability import (
    CloudabilitySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudabilitySource(SimpleSource[CloudabilitySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDABILITY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDABILITY,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Apptio Cloudability (IBM)",
            iconPath="/static/services/cloudability.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
