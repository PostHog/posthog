from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codemagic import (
    CodemagicSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodemagicSource(SimpleSource[CodemagicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODEMAGIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODEMAGIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Codemagic (Nevercode Ltd)",
            iconPath="/static/services/codemagic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
