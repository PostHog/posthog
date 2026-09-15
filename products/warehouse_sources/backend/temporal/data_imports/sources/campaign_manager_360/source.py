from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campaignmanager360 import (
    CampaignManager360SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
