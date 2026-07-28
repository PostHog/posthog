from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.powerbiadmin import (
    PowerBiAdminSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PowerBiAdminSource(SimpleSource[PowerBiAdminSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POWERBIADMIN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POWER_BI_ADMIN,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Microsoft (Power BI / Fabric)",
            iconPath="/static/services/power_bi_admin.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
