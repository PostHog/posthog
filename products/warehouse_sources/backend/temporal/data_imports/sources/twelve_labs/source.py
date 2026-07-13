from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TwelveLabsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwelveLabsSource(SimpleSource[TwelveLabsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWELVELABS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TWELVE_LABS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Twelve Labs",
            iconPath="/static/services/twelve_labs.png",
            keywords=["video", "ai", "video understanding", "indexing"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
