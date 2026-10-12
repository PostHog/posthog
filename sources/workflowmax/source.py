from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.workflowmax._config import WorkflowmaxSourceConfig


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
