from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftpurviewaudit import (
    MicrosoftPurviewAuditSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftPurviewAuditSource(SimpleSource[MicrosoftPurviewAuditSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTPURVIEWAUDIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_PURVIEW_AUDIT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft",
            iconPath="/static/services/microsoft_purview_audit.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
