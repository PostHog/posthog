from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.virtuous import (
    VirtuousSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VirtuousSource(SimpleSource[VirtuousSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VIRTUOUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VIRTUOUS,
            category=DataWarehouseSourceCategory.CRM,
            label="Virtuous (Virtuous Software / Virtuous CRM+)",
            iconPath="/static/services/virtuous.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
