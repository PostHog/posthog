from typing import cast

from sources.azure_openai_usage._config import AzureOpenaiUsageSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureOpenaiUsageSource(SimpleSource[AzureOpenaiUsageSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREOPENAIUSAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREOPENAIUSAGE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure OpenAI Service / Azure Monitor)",
            iconPath="/static/services/azure_openai_usage.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
