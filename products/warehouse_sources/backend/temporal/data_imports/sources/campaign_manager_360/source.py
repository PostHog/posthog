from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
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
            name=SchemaExternalDataSourceType.CAMPAIGN_MANAGER360,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["cm360"],
            label="Campaign Manager 360",
            iconPath="/static/services/campaign_manager_360.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
