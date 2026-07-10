from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HeyGenSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HeyGenSource(SimpleSource[HeyGenSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEYGEN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HEY_GEN,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="HeyGen",
            iconPath="/static/services/heygen.png",
            keywords=["ai video", "avatar", "video generation", "heygen"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
