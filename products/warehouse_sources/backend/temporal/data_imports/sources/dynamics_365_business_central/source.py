from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365businesscentral import (
    Dynamics365BusinessCentralSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Dynamics365BusinessCentralSource(SimpleSource[Dynamics365BusinessCentralSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DYNAMICS365BUSINESSCENTRAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DYNAMICS365_BUSINESS_CENTRAL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Microsoft Dynamics 365 Business Central",
            iconPath="/static/services/dynamics_365_business_central.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
