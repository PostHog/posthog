from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firstpromoter import (
    FirstPromoterSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FirstPromoterSource(SimpleSource[FirstPromoterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIRSTPROMOTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIRST_PROMOTER,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["first promoter"],
            label="FirstPromoter",
            iconPath="/static/services/first_promoter.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
