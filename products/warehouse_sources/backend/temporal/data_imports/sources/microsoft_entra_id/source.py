from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    MicrosoftEntraIdSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftEntraIdSource(SimpleSource[MicrosoftEntraIdSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTENTRAID

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_ENTRA_ID,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Entra Id",
            iconPath="/static/services/microsoft_entra_id.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
