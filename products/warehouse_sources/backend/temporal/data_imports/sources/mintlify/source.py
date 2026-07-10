from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MintlifySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MintlifySource(SimpleSource[MintlifySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MINTLIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MINTLIFY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Mintlify",
            iconPath="/static/services/mintlify.png",
            keywords=["docs", "documentation", "analytics", "assistant"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
