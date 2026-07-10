from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ScaleAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ScaleAISource(SimpleSource[ScaleAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCALEAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SCALE_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Scale AI",
            iconPath="/static/services/scale_ai.png",
            keywords=["labeling", "annotation", "rlhf", "training data"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
