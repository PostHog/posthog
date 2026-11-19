from typing import cast

from products.warehouse_sources.sources.microsoft_purview_audit._config import MicrosoftPurviewAuditSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftPurviewAuditSource(SimpleSource[MicrosoftPurviewAuditSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTPURVIEWAUDIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTPURVIEWAUDIT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft",
            iconPath="/static/services/microsoft_purview_audit.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
