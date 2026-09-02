from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hootsuite import (
    HootsuiteSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HootsuiteSource(SimpleSource[HootsuiteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOOTSUITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HOOTSUITE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Hootsuite",
            iconPath="/static/services/hootsuite.png",
            keywords=["social media", "social media management", "scheduling"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
