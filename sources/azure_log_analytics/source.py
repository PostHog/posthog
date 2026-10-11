from typing import cast

from sources.azure_log_analytics._config import AzureLogAnalyticsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureLogAnalyticsSource(SimpleSource[AzureLogAnalyticsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURELOGANALYTICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURELOGANALYTICS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Monitor / Log Analytics)",
            iconPath="/static/services/azure_log_analytics.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
