from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkhq import (
    CheckHQSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CheckHQSource(SimpleSource[CheckHQSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHECKHQ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHECKHQ,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            keywords=["checkhq", "payroll"],
            label="Check",
            iconPath="/static/services/checkhq.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
