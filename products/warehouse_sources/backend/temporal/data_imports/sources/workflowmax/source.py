from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workflowmax import (
    WorkflowmaxSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WorkflowmaxSource(SimpleSource[WorkflowmaxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKFLOWMAX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WORKFLOWMAX,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Workflowmax",
            iconPath="/static/services/workflowmax.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
