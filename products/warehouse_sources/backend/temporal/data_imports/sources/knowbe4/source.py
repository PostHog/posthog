from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.knowbe4 import (
    Knowbe4SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Knowbe4Source(SimpleSource[Knowbe4SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KNOWBE4

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KNOWBE4,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="KnowBe4",
            iconPath="/static/services/knowbe4.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
