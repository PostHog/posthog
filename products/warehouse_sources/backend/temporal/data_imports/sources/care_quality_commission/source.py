from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    CareQualityCommissionSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CareQualityCommissionSource(SimpleSource[CareQualityCommissionSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAREQUALITYCOMMISSION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CARE_QUALITY_COMMISSION,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Care Quality Commission",
            iconPath="/static/services/care_quality_commission.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
