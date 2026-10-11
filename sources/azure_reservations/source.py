from typing import cast

from sources.azure_reservations._config import AzureReservationsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureReservationsSource(SimpleSource[AzureReservationsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURERESERVATIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURERESERVATIONS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Microsoft Azure (Consumption / Cost Management)",
            iconPath="/static/services/azure_reservations.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
