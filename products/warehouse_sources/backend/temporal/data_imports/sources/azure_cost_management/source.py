from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azurecostmanagement import (
    AzureCostManagementSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureCostManagementSource(SimpleSource[AzureCostManagementSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURECOSTMANAGEMENT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AZURE_COST_MANAGEMENT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Microsoft Azure Cost Management",
            iconPath="/static/services/azure_cost_management.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
