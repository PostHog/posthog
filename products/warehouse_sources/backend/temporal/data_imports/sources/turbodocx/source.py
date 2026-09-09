from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.turbodocx import (
    TurboDocxSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TurboDocxSource(SimpleSource[TurboDocxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TURBODOCX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TURBO_DOCX,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="TurboDocx",
            iconPath="/static/services/turbodocx.png",
            keywords=["documents", "document automation", "proposals"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
