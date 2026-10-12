from typing import cast

from sources.azure_policy_insights._config import AzurePolicyInsightsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzurePolicyInsightsSource(SimpleSource[AzurePolicyInsightsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREPOLICYINSIGHTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREPOLICYINSIGHTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure",
            iconPath="/static/services/azure_policy_insights.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
