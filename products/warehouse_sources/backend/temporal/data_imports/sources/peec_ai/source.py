from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PeecAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PeecAISource(SimpleSource[PeecAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PEECAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PEEC_AI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["peec.ai", "peecai", "AI brand visibility", "AI search analytics"],
            label="Peec AI",
            iconPath="/static/services/peec.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
