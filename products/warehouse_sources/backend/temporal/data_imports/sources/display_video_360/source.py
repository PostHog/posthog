from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    DisplayVideo360SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DisplayVideo360Source(SimpleSource[DisplayVideo360SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DISPLAYVIDEO360

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DISPLAY_VIDEO360,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["dv360"],
            label="Display & Video 360",
            iconPath="/static/services/display_video_360.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
