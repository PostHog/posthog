from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.whatsapp_business_management._config import WhatsappBusinessManagementSourceConfig


@SourceRegistry.register
class WhatsappBusinessManagementSource(SimpleSource[WhatsappBusinessManagementSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WHATSAPPBUSINESSMANAGEMENT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WHATSAPPBUSINESSMANAGEMENT,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Meta Platforms - WhatsApp Business Management API (Graph API)",
            iconPath="/static/services/whatsapp_business_management.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
