from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.visma_economic._config import VismaEconomicSourceConfig


@SourceRegistry.register
class VismaEconomicSource(SimpleSource[VismaEconomicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VISMAECONOMIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VISMAECONOMIC,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Visma Economic",
            iconPath="/static/services/visma_economic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
