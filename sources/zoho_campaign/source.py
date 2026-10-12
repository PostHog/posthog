from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zoho_campaign._config import ZohoCampaignSourceConfig


@SourceRegistry.register
class ZohoCampaignSource(SimpleSource[ZohoCampaignSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOCAMPAIGN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHOCAMPAIGN,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Zoho Campaign",
            iconPath="/static/services/zoho_campaign.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
