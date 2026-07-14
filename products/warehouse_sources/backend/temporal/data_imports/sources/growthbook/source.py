from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GrowthBookSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GrowthBookSource(SimpleSource[GrowthBookSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GROWTHBOOK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GROWTH_BOOK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="GrowthBook",
            iconPath="/static/services/growthbook.png",
            keywords=["feature flags", "experiments", "ab testing", "growthbook"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
