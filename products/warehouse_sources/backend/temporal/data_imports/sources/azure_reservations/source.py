from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azurereservations import (
    AzureReservationsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureReservationsSource(SimpleSource[AzureReservationsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURERESERVATIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AZURE_RESERVATIONS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Microsoft Azure (Consumption / Cost Management)",
            iconPath="/static/services/azure_reservations.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
