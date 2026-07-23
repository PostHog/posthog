from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.npmregistry import (
    NpmRegistrySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NpmRegistrySource(SimpleSource[NpmRegistrySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NPMREGISTRY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NPM_REGISTRY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="npm, Inc. (GitHub / Microsoft)",
            iconPath="/static/services/npm_registry.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
