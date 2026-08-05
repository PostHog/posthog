from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftpurview import (
    MicrosoftPurviewSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftPurviewSource(SimpleSource[MicrosoftPurviewSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTPURVIEW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_PURVIEW,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Purview (Azure)",
            iconPath="/static/services/microsoft_purview.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
