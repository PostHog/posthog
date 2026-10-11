from typing import cast

from sources.deelflows._config import DeelFlowsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DeelFlowsSource(SimpleSource[DeelFlowsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEELFLOWS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DEELFLOWS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="DeelFlows",
            iconPath="/static/services/deelflows.png",
            keywords=["whatsapp", "cart recovery", "marketing automation"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
