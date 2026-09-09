from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leadsquared import (
    LeadSquaredSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LeadSquaredSource(SimpleSource[LeadSquaredSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEADSQUARED

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LEAD_SQUARED,
            category=DataWarehouseSourceCategory.CRM,
            label="LeadSquared",
            iconPath="/static/services/leadsquared.png",
            keywords=["lsq", "marketing automation"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
