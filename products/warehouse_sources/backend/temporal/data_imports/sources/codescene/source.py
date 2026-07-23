from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codescene import (
    CodesceneSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodesceneSource(SimpleSource[CodesceneSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODESCENE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODESCENE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="CodeScene",
            iconPath="/static/services/codescene.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
