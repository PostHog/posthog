from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JellyfishSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JellyfishSource(SimpleSource[JellyfishSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JELLYFISH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JELLYFISH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Jellyfish (Jellyfish Software, Inc.)",
            iconPath="/static/services/jellyfish.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
