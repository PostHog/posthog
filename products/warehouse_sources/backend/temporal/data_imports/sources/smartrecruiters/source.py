from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartrecruiters import (
    SmartrecruitersSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SmartrecruitersSource(SimpleSource[SmartrecruitersSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTRECRUITERS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SMARTRECRUITERS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="SmartRecruiters",
            iconPath="/static/services/smartrecruiters.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
