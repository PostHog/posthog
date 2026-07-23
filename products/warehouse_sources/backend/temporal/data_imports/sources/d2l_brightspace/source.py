from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.d2lbrightspace import (
    D2lBrightspaceSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class D2lBrightspaceSource(SimpleSource[D2lBrightspaceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.D2LBRIGHTSPACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.D2L_BRIGHTSPACE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="D2L Brightspace",
            iconPath="/static/services/d2l_brightspace.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
