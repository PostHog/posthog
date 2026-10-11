from typing import cast

from sources.campaign_manager_360._config import CampaignManager360SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CampaignManager360Source(SimpleSource[CampaignManager360SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAMPAIGNMANAGER360

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CAMPAIGNMANAGER360,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["cm360"],
            label="Campaign Manager 360",
            iconPath="/static/services/campaign_manager_360.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
