from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thoughtspot import (
    ThoughtspotSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ThoughtspotSource(SimpleSource[ThoughtspotSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THOUGHTSPOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.THOUGHTSPOT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="ThoughtSpot",
            iconPath="/static/services/thoughtspot.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
