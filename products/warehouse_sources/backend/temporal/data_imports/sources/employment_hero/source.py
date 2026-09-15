from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.employmenthero import (
    EmploymentHeroSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EmploymentHeroSource(SimpleSource[EmploymentHeroSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EMPLOYMENTHERO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EMPLOYMENTHERO,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Employment-Hero",
            iconPath="/static/services/employment_hero.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
