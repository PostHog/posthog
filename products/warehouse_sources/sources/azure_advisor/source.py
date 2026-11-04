from typing import cast

from products.warehouse_sources.sources.azure_advisor._config import AzureAdvisorSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureAdvisorSource(SimpleSource[AzureAdvisorSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREADVISOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREADVISOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure",
            iconPath="/static/services/azure_advisor.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
