from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sequenzy import (
    SequenzySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SequenzySource(SimpleSource[SequenzySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEQUENZY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SEQUENZY,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Sequenzy",
            iconPath="/static/services/sequenzy.png",
            keywords=["email marketing", "newsletter"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
