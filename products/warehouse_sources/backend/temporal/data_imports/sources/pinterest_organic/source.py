from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pinterestorganic import (
    PinterestOrganicSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PinterestOrganicSource(SimpleSource[PinterestOrganicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PINTERESTORGANIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PINTEREST_ORGANIC,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Pinterest (Pinterest API v5, organic content)",
            iconPath="/static/services/pinterest_organic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
